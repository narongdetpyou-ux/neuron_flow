"""The five cooperating components of the runtime.

Agents are trusted importable Python functions executing in reusable child
processes. A child can be terminated on timeout; only the controller writes
state and only the terminal creates the built-in output artifact.
"""

from dataclasses import dataclass
import hashlib
import importlib
import json
import multiprocessing as mp
from multiprocessing.connection import wait
import os
from pathlib import Path
import tempfile
import threading
import time

from .model import (MAX_MESSAGE_BYTES, MessageSizeError, SpecError, TransientAgentError,
                    encode, fingerprint, normalize_spec)
from .storage import Store, WorkspaceLock


_DELIVERY_ERROR_PREFIX = "neuron-flow-structured-error:"


def _error_record(exc, error_type=None):
    error = {"type": error_type or type(exc).__name__, "message": str(exc)[:1000]}
    from .supervision import OperationFailure
    if isinstance(exc, OperationFailure):
        error.update(exc.details)
    if isinstance(exc, MessageSizeError):
        error.update(exc.details())
        if error_type is not None:
            error["cause"] = type(exc).__name__
    return error


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    entrypoint: str
    validator: object
    version: str = "1"


def _exit_when_parent_dies():
    parent = mp.parent_process()
    if parent is not None:
        try:
            wait([parent.sentinel])
        finally:
            os._exit(71)


def _worker_main(connection):
    # A controller killed during a hung task must not leave an orphan worker.
    threading.Thread(target=_exit_when_parent_dies, daemon=True).start()
    try:
        connection.send_bytes(encode({"kind": "ready"}))
        while True:
            try:
                command = json.loads(connection.recv_bytes(MAX_MESSAGE_BYTES))
            except EOFError:
                return
            if command["kind"] == "stop":
                return
            work_id = command["message"]["work_id"]
            try:
                module_name, function_name = command["entrypoint"].split(":", 1)
                function = getattr(importlib.import_module(module_name), function_name)
                output = function(command["message"])
                response = encode({"kind": "result", "work_id": work_id, "output": output,
                                   "finished": time.monotonic()}, phase="agent_response")
            except BaseException as exc:
                # SystemExit is an agent failure, not permission to stop the controller.
                response = encode({"kind": "error", "work_id": work_id,
                                   "finished": time.monotonic(),
                                   "retryable": isinstance(exc, TransientAgentError),
                                   "error": _error_record(exc)}, phase="agent_error_response")
            connection.send_bytes(response)
    finally:
        connection.close()


class Worker:
    def __init__(self):
        context = mp.get_context("spawn")
        self.connection, child = context.Pipe()
        self.process = context.Process(target=_worker_main, args=(child,), daemon=True)
        self.busy = None
        try:
            self.process.start()
            child.close()
            if not self.connection.poll(10):
                raise RuntimeError("Worker startup timed out")
            if json.loads(self.connection.recv_bytes(MAX_MESSAGE_BYTES)) != {"kind": "ready"}:
                raise RuntimeError("Invalid worker startup handshake")
        except BaseException:
            child.close()
            self.close()
            raise

    def dispatch(self, definition, message, step):
        data = encode({"kind": "run", "entrypoint": definition.entrypoint, "message": message},
                      phase="agent_request")
        started = time.monotonic()
        self.connection.send_bytes(data)
        self.busy = {"message": message, "step": step, "started": started}

    def close(self):
        # Always kill a busy worker. A graceful stop message would wait behind
        # a hung task and could block on a pipe that the task never reads.
        if self.process.pid is not None:
            if self.process.is_alive():
                self.process.terminate()
            self.process.join(1)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(1)
        self.connection.close()


class Synapse:
    """Contracts and targeted, durable event routing."""

    def __init__(self, store, definitions, validation_timeout_s=None):
        self.store = store
        self.validation_timeout_s = validation_timeout_s
        if validation_timeout_s is not None:
            from .supervision import number
            number(validation_timeout_s, .05, 3600, "validation_timeout_s")
        self.agents = {}
        for definition in definitions:
            if (definition.name in self.agents or not callable(definition.validator)
                    or not isinstance(definition.version, str) or not definition.version
                    or ":" not in definition.entrypoint):
                raise ValueError("Each agent needs a unique name, entrypoint and validator")
            self.agents[definition.name] = definition

    def validate(self, agent_name, message, output):
        # Reject NaN, huge outputs, and non-JSON objects before persistence.
        before = encode(output, phase="agent_output_validation")
        validator = self.agents[agent_name].validator
        if self.validation_timeout_s is None:
            result = validator(message, output)
        else:
            from .supervision import isolated
            result = isolated("neuron_flow.supervision:validate_agent", {
                "validator": f"{validator.__module__}:{validator.__qualname__}",
                "message": message, "output": output}, self.validation_timeout_s, phase="validation")
        if result is not None and result is not True:
            raise ValueError("Validator rejected the result; return None/True or raise an error")
        if before != encode(output, phase="agent_output_validation"):
            raise ValueError("Validator must check results without modifying them")

    def identity(self, name):
        definition = self.agents[name]
        result = {"entrypoint": definition.entrypoint, "version": definition.version}
        if self.validation_timeout_s is not None:
            result["validation_timeout_s"] = self.validation_timeout_s
        return result

    def audience(self, step_id, spec):
        return [f"step:{step['id']}" for step in spec["steps"] if step_id in step["depends_on"]]

    def events_for(self, recipient, job_id, after=0):
        return self.store.events_for(recipient, job_id, after)


class Dendrite:
    """Validate raw input and create durable tasks; duplicate jobs are reused."""

    def __init__(self, store, synapse):
        self.store, self.synapse = store, synapse

    def submit(self, spec):
        normalized = normalize_spec(spec, self.synapse.agents)
        normalized["agent_versions"] = {
            step["agent"]: self.synapse.identity(step["agent"])
            for step in normalized["steps"]
        }
        # Normalization and Agent metadata can make the stored workflow larger
        # than its original source spec, which may have fit within the cap.
        encode(normalized, phase="workflow_submission")
        created = self.store.submit(normalized)
        return {"job_id": normalized["job_id"], "created": created}

    def ingest(self, raw_input, job_id=None):
        """Select the supported invoice workflow directly from structured input."""
        if not isinstance(raw_input, dict) or not {"document_id", "items"} <= raw_input.keys():
            raise SpecError("Unsupported input: expected a structured invoice with document_id and items")
        from .agents import invoice_workflow
        identifier = job_id if job_id is not None else f"invoice_{fingerprint(raw_input)[:16]}"
        return self.submit(invoice_workflow(raw_input, identifier))


class Axon:
    """Route a step only to its registered capability and declared inputs."""

    def __init__(self, synapse):
        self.synapse = synapse

    def prepare(self, spec, step, state, attempt):
        message = {
            "work_id": f"{spec['job_id']}:{step['id']}:{attempt}",
            "job_id": spec["job_id"], "step_id": step["id"], "attempt": attempt,
            "input": spec["input"], "params": step["params"],
            "dependencies": {dep: state[dep]["output"] for dep in step["depends_on"]},
        }
        # Preflight the complete command before allocating a worker. Its input
        # and dependency outputs may fit separately yet overflow when combined.
        definition = self.synapse.agents[step["agent"]]
        command = {"kind": "run", "entrypoint": definition.entrypoint, "message": message}
        detached = json.loads(encode(command, phase="agent_request"))
        return definition, detached["message"]


class AxonTerminal:
    """One idempotent local report action, with a verified receipt."""

    def __init__(self, output_dir):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def deliver(self, report):
        data = encode(report, phase="terminal_report") + b"\n"
        if len(data) > MAX_MESSAGE_BYTES:
            raise MessageSizeError(len(data), phase="terminal_report")
        path = self.output_dir / f"{report['job_id']}.json"
        digest = hashlib.sha256(data).hexdigest()
        if path.exists():
            if path.read_bytes() != data:
                raise RuntimeError("Existing report differs; preserve it and inspect the conflict")
        else:
            descriptor, temporary = tempfile.mkstemp(prefix=".report-", dir=self.output_dir)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
                # Persist directory metadata on systems that support it.
                if os.name != "nt":
                    directory = os.open(self.output_dir, os.O_RDONLY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
            finally:
                Path(temporary).unlink(missing_ok=True)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError("Report read-back verification failed")
        return {"path": str(path.resolve()), "sha256": digest, "bytes": len(data)}


class Soma:
    """Bounded scheduling, supervision, recovery and independent validation."""

    def __init__(self, store, synapse, axon, terminal, max_workers, telemetry=None):
        self.store, self.synapse, self.axon, self.terminal = store, synapse, axon, terminal
        self.max_workers = max_workers
        self.workers = []
        self.peak_workers = 0
        self.telemetry = telemetry

    def _failure(self, spec, step, attempt, error, retryable):
        retry = retryable and attempt < step["max_attempts"]
        self.store.transition(spec["job_id"], step["id"], "RETRY_WAIT" if retry else "FAILED", attempt,
                              error=error, ready_at=time.time() + step["retry_delay_s"] if retry else 0,
                              audience=self.synapse.audience(step["id"], spec))

    def recover(self, spec):
        state = self.store.steps(spec["job_id"])
        for step in spec["steps"]:
            previous = state[step["id"]]
            if previous["status"] == "RUNNING":
                self._failure(spec, step, previous["attempts"],
                              {"type": "ControllerInterrupted", "message": "Previous controller stopped during this attempt"}, True)

    def _collect(self, spec):
        for worker in list(self.workers):
            if worker.busy is None:
                if not worker.process.is_alive():
                    worker.close()
                    self.workers.remove(worker)
                continue
            busy = worker.busy
            message, step = busy["message"], busy["step"]
            expired = time.monotonic() - busy["started"] >= step["timeout_s"]
            try:
                if not worker.connection.poll():
                    if expired:
                        raise TimeoutError(f"Agent exceeded {step['timeout_s']} seconds")
                    if not worker.process.is_alive():
                        raise ChildProcessError("Agent worker exited without a result")
                    continue
                response = json.loads(worker.connection.recv_bytes(MAX_MESSAGE_BYTES))
                if response.get("work_id") != message["work_id"]:
                    raise ChildProcessError("Worker reply does not match its assigned work")
                if response.get("finished", float("inf")) - busy["started"] >= step["timeout_s"]:
                    raise TimeoutError(f"Agent exceeded {step['timeout_s']} seconds")
                if self.telemetry is not None:
                    phase = {"csv_validate": "validation", "csv_calculate": "calculation", "csv_verify": "verification"}.get(step['agent'], 'agent')
                    self.telemetry.record(phase, max(0, (response.get('finished', time.monotonic()) - busy['started']) * 1000),
                                          'ERROR' if response.get('kind') == 'error' else 'OK')
                if response.get("kind") == "error":
                    self._failure(spec, step, message["attempt"], response["error"], response["retryable"])
                elif response.get("kind") == "result":
                    validation_started = time.monotonic()
                    validation_outcome = 'ERROR'
                    try:
                        self.synapse.validate(step["agent"], message, response["output"])
                    except Exception as exc:
                        self._failure(spec, step, message["attempt"],
                                      _error_record(exc, "OutputValidationError"), False)
                    else:
                        validation_outcome = 'OK'
                        self.store.transition(spec["job_id"], step["id"], "SUCCEEDED", message["attempt"],
                                              output=response["output"],
                                              audience=self.synapse.audience(step["id"], spec))
                    finally:
                        if self.telemetry is not None:
                            self.telemetry.record('contract_validation', (time.monotonic() - validation_started) * 1000, validation_outcome)
                else:
                    raise ChildProcessError("Unknown worker response")
                worker.busy = None
            except (TimeoutError, ChildProcessError, EOFError, OSError, ValueError) as exc:
                worker.close()
                self.workers.remove(worker)
                self._failure(spec, step, message["attempt"],
                              {"type": type(exc).__name__, "message": str(exc)[:1000]}, True)

    def run(self, job_id):
        job = self.store.job(job_id)
        spec = job["spec"]
        for step in spec["steps"]:
            if step["agent"] not in self.synapse.agents:
                raise SpecError(f"Agent no longer registered: {step['agent']}")
            if spec["agent_versions"][step["agent"]] != self.synapse.identity(step["agent"]):
                raise SpecError(f"Agent version changed: {step['agent']}; use a new job id or restore its original definition")
        self.recover(spec)
        self.store.job_status(job_id, "RUNNING")
        while True:
            self._collect(spec)
            state = self.store.steps(job_id)
            for step in spec["steps"]:
                current = state[step["id"]]
                if current["status"] not in {"PENDING", "RETRY_WAIT"}:
                    continue
                if any(state[dep]["status"] in {"FAILED", "BLOCKED"} for dep in step["depends_on"]):
                    self.store.transition(job_id, step["id"], "BLOCKED", current["attempts"],
                                          error={"type": "DependencyFailed", "message": "A required step did not succeed"},
                                          audience=self.synapse.audience(step["id"], spec))
                    current["status"] = "BLOCKED"
                    continue
                if (not all(state[dep]["status"] == "SUCCEEDED" for dep in step["depends_on"])
                        or current["ready_at"] > time.time()):
                    continue
                idle = next((worker for worker in self.workers if worker.busy is None), None)
                if idle is None and len(self.workers) >= self.max_workers:
                    continue
                attempt = current["attempts"] + 1
                self.store.transition(job_id, step["id"], "RUNNING", attempt)
                try:
                    definition, message = self.axon.prepare(spec, step, state, attempt)
                    if idle is None:
                        idle = Worker()
                        self.workers.append(idle)
                        self.peak_workers = max(self.peak_workers, len(self.workers))
                    idle.dispatch(definition, message, step)
                except SpecError as exc:
                    self._failure(spec, step, attempt, _error_record(exc, "InputContractError"), False)
                except (OSError, RuntimeError, EOFError) as exc:
                    if idle is not None:
                        idle.close()
                        if idle in self.workers:
                            self.workers.remove(idle)
                    self._failure(spec, step, attempt, {"type": "WorkerStartError", "message": str(exc)[:1000]}, True)
            state = self.store.steps(job_id)
            if all(value["status"] in {"SUCCEEDED", "FAILED", "BLOCKED"} for value in state.values()):
                break
            time.sleep(0.01)
        status = "SUCCEEDED" if all(value["status"] == "SUCCEEDED" for value in state.values()) else "FAILED"
        report = {"job_id": job_id, "status": status, "steps": {
            key: {field: value[field] for field in ("status", "attempts", "output", "error")}
            for key, value in state.items()
        }}
        delivery_started = time.monotonic()
        delivery_outcome = 'ERROR'
        try:
            receipt = self.terminal.deliver(report)
        except Exception as exc:
            error = str(exc)[:1000]
            if isinstance(exc, MessageSizeError):
                # Keep the existing TEXT column and readable snapshot field.
                # A reserved prefix distinguishes our record from old messages.
                error = _DELIVERY_ERROR_PREFIX + json.dumps(_error_record(exc), sort_keys=True)
            self.store.job_status(job_id, "DELIVERY_FAILED", error=error)
        else:
            delivery_outcome = 'OK'
            self.store.job_status(job_id, status, receipt=receipt)
        finally:
            if self.telemetry is not None:
                self.telemetry.record('delivery', (time.monotonic() - delivery_started) * 1000, delivery_outcome)
        return self.snapshot(job_id)

    def snapshot(self, job_id):
        job = self.store.job(job_id)
        result = {"job_id": job_id, "status": job["status"], "receipt": job["receipt"],
                  "delivery_error": job["delivery_error"], "steps": self.store.steps(job_id),
                  "peak_workers": self.peak_workers}
        error = job["delivery_error"]
        if isinstance(error, str) and error.startswith(_DELIVERY_ERROR_PREFIX):
            try:
                details = json.loads(error[len(_DELIVERY_ERROR_PREFIX):])
            except (ValueError, TypeError):
                details = None
            if (isinstance(details, dict) and details.get("type") == "MessageSizeError"
                    and isinstance(details.get("message"), str)):
                result["delivery_error"] = details["message"]
                result["delivery_error_details"] = details
        return result

    def close(self):
        for worker in self.workers:
            worker.close()
        self.workers.clear()


class Runtime:
    """Own exactly one workspace. Use as a context manager."""

    def __init__(self, workspace, *, max_workers=3, agents=None, validation_timeout_s=None, telemetry=None):
        if type(max_workers) is not int or not 1 <= max_workers <= 32:
            raise ValueError("max_workers must be between 1 and 32")
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.lock = WorkspaceLock(self.workspace / "runtime.lock")
        self.store = None
        self.soma = None
        self.closed = False
        try:
            if agents is None:
                from .agents import default_agents
                agents = default_agents()
            self.store = Store(self.workspace / "state.sqlite3")
            self.synapse = Synapse(self.store, agents, validation_timeout_s)
            self.dendrite = Dendrite(self.store, self.synapse)
            self.axon = Axon(self.synapse)
            self.terminal = AxonTerminal(self.workspace / "reports")
            self.soma = Soma(self.store, self.synapse, self.axon, self.terminal, max_workers, telemetry)
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        if self.closed:
            raise RuntimeError("Runtime is closed")
        return self

    def __exit__(self, *_):
        self.close()

    def submit(self, spec):
        self.__enter__()
        return self.dendrite.submit(spec)

    def ingest(self, raw_input, job_id=None):
        self.__enter__()
        return self.dendrite.ingest(raw_input, job_id)

    def run(self, job_id):
        self.__enter__()
        try:
            return self.soma.run(job_id)
        except BaseException:
            # No live attempt may be recovered/retried while its old worker runs.
            self.soma.close()
            raise

    def status(self, job_id):
        self.__enter__()
        return self.soma.snapshot(job_id)

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if self.soma is not None:
                self.soma.close()
            if self.store is not None:
                self.store.close()
        finally:
            self.lock.close()
