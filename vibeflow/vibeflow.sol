// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * VibeFlow (Production-ish, SKALE-friendly, "put a lot on-chain")
 * --------------------------------------------------------------
 * A Temporal-inspired workflow engine implemented as an on-chain "server":
 *
 * Key Temporal-like features included:
 *  ✅ Durable workflows + event history (event-sourcing) ON-CHAIN
 *  ✅ Workflow Tasks (a.k.a. decision tasks): deciders claim + complete with commands
 *  ✅ Activity Tasks: workers claim + start + heartbeat + complete/fail
 *  ✅ Task Queues: workers register for queues, claimNext / claimSpecific
 *  ✅ Single-assignment with leasing: prevents two workers doing same task
 *  ✅ Timeouts: scheduleToStart, startToClose, heartbeat, timer firing
 *  ✅ Retries with backoff: per-activity retry policy stored on-chain
 *  ✅ Signals: external inputs create history events and trigger a new workflow task
 *  ✅ Queries: read workflow state/search attributes/history
 *  ✅ Cancellation: cancel workflow, cancel activity, request cancel external workflow
 *  ✅ Child workflows (basic): start child, completion notifies parent
 *  ✅ Versioning / optimistic concurrency for workflow task completion
 *
 * Not included (but easy extensions):
 *  - Advanced memoization / deterministic side effects helpers
 *  - Nexus / multi-cluster replication
 *  - Visibility indexing (we store attributes; you can index off-chain if desired)
 *
 * Security model (tunable):
 *  - Workflows have an owner (creator) and a deciderQueue (workflow task queue)
 *  - Only deciders (workers registered for the deciderQueue) can claim/complete workflow tasks
 *  - Only activity workers registered for the activity task queue can claim/start/complete activities
 *  - Anyone can "tick" timeouts/timers (like Temporal's server scanners)
 *
 * WARNING:
 *  - This is a large, feature-rich skeleton. Audit + threat model for production.
 *  - If you want stronger guarantees vs MEV or griefing, add staking/slashing + commit-reveal claims.
 */
contract VibeFlow {
    // ------------------------------------------------------------
    // Roles / Admin (simple)
    // ------------------------------------------------------------
    address public admin;

    modifier onlyAdmin() {
        require(msg.sender == admin, "VibeFlow: not admin");
        _;
    }

    constructor() {
        admin = msg.sender;
    }

    function transferAdmin(address newAdmin) external onlyAdmin {
        require(newAdmin != address(0), "VibeFlow: admin=0");
        admin = newAdmin;
    }

    // ------------------------------------------------------------
    // Enums
    // ------------------------------------------------------------

    enum WorkflowStatus { NONE, RUNNING, COMPLETED, FAILED, CANCELED, TERMINATED }

    enum WorkflowTaskStatus { NONE, SCHEDULED, CLAIMED, COMPLETED, TIMED_OUT, CANCELED }

    enum ActivityStatus { NONE, SCHEDULED, CLAIMED, STARTED, SUCCEEDED, FAILED, TIMED_OUT, CANCELED }

    enum HistoryEventType {
        // Workflow lifecycle
        WORKFLOW_STARTED,
        WORKFLOW_TASK_SCHEDULED,
        WORKFLOW_TASK_STARTED,
        WORKFLOW_TASK_COMPLETED,
        WORKFLOW_COMPLETED,
        WORKFLOW_FAILED,
        WORKFLOW_CANCELED,
        WORKFLOW_TERMINATED,

        // Activities
        ACTIVITY_SCHEDULED,
        ACTIVITY_TASK_CLAIMED,
        ACTIVITY_STARTED,
        ACTIVITY_HEARTBEAT,
        ACTIVITY_COMPLETED,
        ACTIVITY_FAILED,
        ACTIVITY_TIMED_OUT,
        ACTIVITY_CANCELED,

        // Timers
        TIMER_SCHEDULED,
        TIMER_FIRED,
        TIMER_CANCELED,

        // Signals
        SIGNAL_RECEIVED,

        // Child workflows
        CHILD_WORKFLOW_STARTED,
        CHILD_WORKFLOW_COMPLETED,
        CHILD_WORKFLOW_FAILED,
        CHILD_WORKFLOW_CANCELED,

        // Markers / attributes
        MARKER_RECORDED,
        SEARCH_ATTRIBUTES_UPSERTED,

        // External workflow interactions
        REQUEST_CANCEL_EXTERNAL_WORKFLOW
    }

    enum CommandType {
        // schedule work
        SCHEDULE_ACTIVITY,
        START_TIMER,

        // workflow completion
        COMPLETE_WORKFLOW,
        FAIL_WORKFLOW,
        CANCEL_WORKFLOW,
        TERMINATE_WORKFLOW,

        // activity control
        CANCEL_ACTIVITY,

        // signals / external
        RECORD_MARKER,
        UPSERT_SEARCH_ATTRIBUTES,
        REQUEST_CANCEL_EXTERNAL_WORKFLOW,

        // child workflows
        START_CHILD_WORKFLOW
    }

    // ------------------------------------------------------------
    // Core structs
    // ------------------------------------------------------------

    struct RetryPolicy {
        bool enabled;
        uint8 maxAttempts;          // total attempts (including first)
        uint32 initialIntervalSec;  // base delay
        uint32 backoffMultiplierBP; // 20000 => 2.0x
        uint32 maxIntervalSec;      // cap
    }

    struct ActivityTimeouts {
        uint32 scheduleToStartSec;  // if not started in time -> timeout
        uint32 startToCloseSec;     // execution time bound once started
        uint32 heartbeatTimeoutSec; // if no heartbeat within -> timeout
    }

    struct Workflow {
        uint256 id;
        uint256 parentWorkflowId;   // 0 if none
        uint256 parentChildId;      // child handle in parent (0 if none)

        address owner;
        WorkflowStatus status;

        bytes32 workflowType;
        bytes32 workflowTaskQueue;  // decider queue

        // deterministic progress / on-chain state (optional)
        bytes input;
        bytes state;                // decider can persist arbitrary state snapshot
        bytes result;               // final output or failure details

        // optimistic concurrency: increments per successful workflow task completion
        uint64 version;

        // history cursoring
        uint64 historyLen;          // cached length for quick reads

        // bookkeeping
        uint64 createdAt;
        uint64 updatedAt;

        // "search attributes" (Temporal visibility-like)
        mapping(bytes32 => bytes) searchAttr;
        bytes32[] searchAttrKeys;
        mapping(bytes32 => bool) searchAttrKeyExists;
    }

    struct HistoryEvent {
        uint64 ts;
        HistoryEventType typ;
        uint256 refId;  // workflowTaskId / activityId / timerId / childId etc
        bytes data;     // FULL payload stored (SKALE-friendly)
    }

    // Workflow Task (decision task)
    struct WorkflowTask {
        uint256 id;
        uint256 workflowId;
        WorkflowTaskStatus status;

        uint64 scheduledAt;
        uint64 startedAt;
        uint64 deadlineAt;   // scheduleToStart-ish for workflow tasks (optional)
        uint64 leaseUntil;

        address assignedDecider;

        // Used for concurrency: decider must complete at this expectedVersion
        uint64 expectedVersion;

        // History position for incremental processing
        uint64 fromHistoryIndex;
    }

    // Activity (activity task)
    struct Activity {
        uint256 id;
        uint256 workflowId;

        bytes32 activityType;
        bytes32 taskQueue;

        ActivityStatus status;

        bytes input;
        bytes result;     // success output
        bytes failure;    // failure details

        RetryPolicy retry;
        ActivityTimeouts timeouts;

        uint8 attempt;
        uint8 maxAttempts;

        uint64 scheduledAt;
        uint64 scheduleToStartDeadlineAt;

        uint64 claimedAt;
        uint64 startedAt;
        uint64 startToCloseDeadlineAt;

        uint64 lastHeartbeatAt;
        uint64 heartbeatDeadlineAt;

        uint64 nextRetryAt;

        address assignedWorker;
        uint64 leaseUntil;

        bool cancelRequested;
    }

    struct Timer {
        uint256 id;
        uint256 workflowId;

        bool open;
        uint64 fireAt;
        bytes payload;
    }

    // Commands submitted by decider when completing a workflow task
    struct Command {
        CommandType typ;
        bytes payload; // abi.encode(...) depending on typ
    }

    // ------------------------------------------------------------
    // IDs
    // ------------------------------------------------------------
    uint256 public nextWorkflowId = 1;
    uint256 public nextWorkflowTaskId = 1;
    uint256 public nextActivityId = 1;
    uint256 public nextTimerId = 1;

    // ------------------------------------------------------------
    // Storage maps
    // ------------------------------------------------------------
    mapping(uint256 => Workflow) private workflows;
    mapping(uint256 => HistoryEvent[]) private history;

    mapping(uint256 => WorkflowTask) public workflowTasks;
    mapping(uint256 => Activity) public activities;
    mapping(uint256 => Timer) public timers;

    mapping(uint256 => uint256[]) public workflowWorkflowTasks;
    mapping(uint256 => uint256[]) public workflowActivities;
    mapping(uint256 => uint256[]) public workflowTimers;
    mapping(uint256 => uint256[]) public workflowChildren; // list of child workflow ids

    // ------------------------------------------------------------
    // Worker registry + queues
    // ------------------------------------------------------------

    // worker => queue => allowed
    mapping(address => mapping(bytes32 => bool)) public workerAllowedOnQueue;

    // queue => list of workflowTaskIds (append-only)
    mapping(bytes32 => uint256[]) private workflowTaskQueue;
    mapping(bytes32 => uint256[]) private activityTaskQueue;

    // worker cursors to make claimNext less repetitive
    mapping(address => mapping(bytes32 => uint256)) private workerCursorWorkflowTask;
    mapping(address => mapping(bytes32 => uint256)) private workerCursorActivityTask;

    // ------------------------------------------------------------
    // Defaults (can be configured by admin)
    // ------------------------------------------------------------

    uint32 public defaultWorkflowTaskScheduleToStartSec = 120; // decider must claim in 2 mins (tune)
    uint32 public defaultTaskLeaseSec = 60;                    // lease for claims

    RetryPolicy public defaultRetry = RetryPolicy({
        enabled: true,
        maxAttempts: 5,
        initialIntervalSec: 10,
        backoffMultiplierBP: 20000,
        maxIntervalSec: 3600
    });

    ActivityTimeouts public defaultActivityTimeouts = ActivityTimeouts({
        scheduleToStartSec: 300,
        startToCloseSec: 300,
        heartbeatTimeoutSec: 60
    });

    function setDefaults(
        uint32 workflowTaskScheduleToStartSec,
        uint32 taskLeaseSec,
        RetryPolicy calldata retry,
        ActivityTimeouts calldata timeouts
    ) external onlyAdmin {
        require(workflowTaskScheduleToStartSec > 0, "VibeFlow: bad WT timeout");
        require(taskLeaseSec > 0, "VibeFlow: bad lease");
        defaultWorkflowTaskScheduleToStartSec = workflowTaskScheduleToStartSec;
        defaultTaskLeaseSec = taskLeaseSec;

        defaultRetry = retry;
        defaultActivityTimeouts = timeouts;
    }

    // ------------------------------------------------------------
    // Events (for off-chain watchers)
    // ------------------------------------------------------------
    event WorkerQueuePermission(address indexed worker, bytes32 indexed queue, bool allowed);

    event WorkflowStarted(uint256 indexed workflowId, bytes32 indexed workflowType, bytes32 indexed workflowTaskQueue);
    event WorkflowTaskScheduled(uint256 indexed workflowTaskId, uint256 indexed workflowId, bytes32 indexed queue);
    event WorkflowTaskClaimed(uint256 indexed workflowTaskId, uint256 indexed workflowId, address decider, uint64 leaseUntil);
    event WorkflowTaskCompleted(uint256 indexed workflowTaskId, uint256 indexed workflowId, uint64 newVersion);

    event ActivityScheduled(uint256 indexed activityId, uint256 indexed workflowId, bytes32 indexed activityType, bytes32 queue, uint8 attempt);
    event ActivityClaimed(uint256 indexed activityId, uint256 indexed workflowId, address worker, uint64 leaseUntil);
    event ActivityStarted(uint256 indexed activityId, uint256 indexed workflowId, address worker);
    event ActivityCompleted(uint256 indexed activityId, uint256 indexed workflowId);
    event ActivityFailed(uint256 indexed activityId, uint256 indexed workflowId, bool willRetry, uint64 nextRetryAt);
    event ActivityTimedOut(uint256 indexed activityId, uint256 indexed workflowId, bool willRetry, uint64 nextRetryAt);
    event ActivityCanceled(uint256 indexed activityId, uint256 indexed workflowId);

    event TimerScheduled(uint256 indexed timerId, uint256 indexed workflowId, uint64 fireAt);
    event TimerFired(uint256 indexed timerId, uint256 indexed workflowId);

    event SignalReceived(uint256 indexed workflowId, bytes32 indexed signalType);

    event WorkflowCompleted(uint256 indexed workflowId);
    event WorkflowFailed(uint256 indexed workflowId);
    event WorkflowCanceled(uint256 indexed workflowId);
    event WorkflowTerminated(uint256 indexed workflowId);

    event ChildWorkflowStarted(uint256 indexed parentWorkflowId, uint256 indexed childWorkflowId, uint256 indexed parentChildId);
    event ChildWorkflowCompleted(uint256 indexed parentWorkflowId, uint256 indexed childWorkflowId);
    event ChildWorkflowFailed(uint256 indexed parentWorkflowId, uint256 indexed childWorkflowId);
    event ChildWorkflowCanceled(uint256 indexed parentWorkflowId, uint256 indexed childWorkflowId);

    // ------------------------------------------------------------
    // Worker registration
    // ------------------------------------------------------------

    function setWorkerQueuePermission(address worker, bytes32 queue, bool allowed) external onlyAdmin {
        require(worker != address(0), "VibeFlow: worker=0");
        require(queue != bytes32(0), "VibeFlow: queue=0");
        workerAllowedOnQueue[worker][queue] = allowed;
        emit WorkerQueuePermission(worker, queue, allowed);
    }

    // Open registration alternative (if you want):
    function registerSelfOnQueue(bytes32 queue, bool allowed) external {
        require(queue != bytes32(0), "VibeFlow: queue=0");
        workerAllowedOnQueue[msg.sender][queue] = allowed;
        emit WorkerQueuePermission(msg.sender, queue, allowed);
    }

    // ------------------------------------------------------------
    // Workflow start / read
    // ------------------------------------------------------------

    function startWorkflow(
        bytes32 workflowType,
        bytes32 workflowTaskQueueName,
        bytes calldata input,
        bytes calldata initialState,
        bytes32[] calldata searchKeys,
        bytes[] calldata searchValues
    ) external returns (uint256 workflowId) {
        require(workflowType != bytes32(0), "VibeFlow: workflowType=0");
        require(workflowTaskQueueName != bytes32(0), "VibeFlow: wtQueue=0");
        require(searchKeys.length == searchValues.length, "VibeFlow: search len mismatch");

        workflowId = nextWorkflowId++;

        Workflow storage wf = workflows[workflowId];
        wf.id = workflowId;
        wf.owner = msg.sender;
        wf.status = WorkflowStatus.RUNNING;
        wf.workflowType = workflowType;
        wf.workflowTaskQueue = workflowTaskQueueName;
        wf.input = input;
        wf.state = initialState;
        wf.version = 0;
        wf.createdAt = uint64(block.timestamp);
        wf.updatedAt = uint64(block.timestamp);

        // search attributes
        for (uint256 i = 0; i < searchKeys.length; i++) {
            _upsertSearchAttr(wf, searchKeys[i], searchValues[i]);
        }

        _appendHistory(workflowId, HistoryEventType.WORKFLOW_STARTED, 0, abi.encode(workflowType, workflowTaskQueueName, input, initialState));

        emit WorkflowStarted(workflowId, workflowType, workflowTaskQueueName);

        // schedule initial workflow task
        _scheduleWorkflowTask(workflowId, /*fromHistoryIndex*/ 0);
    }

    function getWorkflow(uint256 workflowId)
        external
        view
        returns (
            address owner,
            WorkflowStatus status,
            bytes32 workflowType,
            bytes32 workflowTaskQueueName,
            uint32 /* step placeholder */,
            uint64 version,
            bytes memory input,
            bytes memory state,
            bytes memory result,
            uint64 createdAt,
            uint64 updatedAt,
            uint64 historyLength_
        )
    {
        Workflow storage wf = workflows[workflowId];
        owner = wf.owner;
        status = wf.status;
        workflowType = wf.workflowType;
        workflowTaskQueueName = wf.workflowTaskQueue;
        version = wf.version;
        input = wf.input;
        state = wf.state;
        result = wf.result;
        createdAt = wf.createdAt;
        updatedAt = wf.updatedAt;
        historyLength_ = uint64(history[workflowId].length);
    }

    function getSearchAttribute(uint256 workflowId, bytes32 key) external view returns (bytes memory) {
        Workflow storage wf = workflows[workflowId];
        return wf.searchAttr[key];
    }

    function listSearchAttributeKeys(uint256 workflowId) external view returns (bytes32[] memory) {
        Workflow storage wf = workflows[workflowId];
        return wf.searchAttrKeys;
    }

    // History reads
    function historyLength(uint256 workflowId) external view returns (uint256) {
        return history[workflowId].length;
    }

    function getHistoryEvent(uint256 workflowId, uint256 idx) external view returns (HistoryEvent memory) {
        return history[workflowId][idx];
    }

    function getHistoryRange(uint256 workflowId, uint256 from, uint256 toInclusive) external view returns (HistoryEvent[] memory out) {
        require(toInclusive >= from, "VibeFlow: bad range");
        HistoryEvent[] storage h = history[workflowId];
        require(toInclusive < h.length, "VibeFlow: OOB");
        uint256 n = toInclusive - from + 1;
        out = new HistoryEvent[](n);
        for (uint256 i = 0; i < n; i++) {
            out[i] = h[from + i];
        }
    }

    // ------------------------------------------------------------
    // Signals
    // ------------------------------------------------------------

    function signalWorkflow(uint256 workflowId, bytes32 signalType, bytes calldata data) external {
        Workflow storage wf = workflows[workflowId];
        require(wf.status == WorkflowStatus.RUNNING, "VibeFlow: not running");
        require(signalType != bytes32(0), "VibeFlow: signalType=0");

        _appendHistory(workflowId, HistoryEventType.SIGNAL_RECEIVED, 0, abi.encode(msg.sender, signalType, data));
        emit SignalReceived(workflowId, signalType);

        _scheduleWorkflowTask(workflowId, uint64(history[workflowId].length) - 1);
    }

    // ------------------------------------------------------------
    // Workflow Tasks (decider tasks)
    // ------------------------------------------------------------

    function _scheduleWorkflowTask(uint256 workflowId, uint64 fromHistoryIndex) internal {
        Workflow storage wf = workflows[workflowId];
        require(wf.status == WorkflowStatus.RUNNING, "VibeFlow: not running");

        uint256 wtid = nextWorkflowTaskId++;
        WorkflowTask storage wt = workflowTasks[wtid];
        wt.id = wtid;
        wt.workflowId = workflowId;
        wt.status = WorkflowTaskStatus.SCHEDULED;
        wt.scheduledAt = uint64(block.timestamp);
        wt.deadlineAt = uint64(block.timestamp + defaultWorkflowTaskScheduleToStartSec);
        wt.leaseUntil = 0;
        wt.assignedDecider = address(0);
        wt.expectedVersion = wf.version;
        wt.fromHistoryIndex = fromHistoryIndex;

        workflowWorkflowTasks[workflowId].push(wtid);
        workflowTaskQueue[wf.workflowTaskQueue].push(wtid);

        _appendHistory(workflowId, HistoryEventType.WORKFLOW_TASK_SCHEDULED, wtid, abi.encode(wtid, wf.workflowTaskQueue, fromHistoryIndex, wf.version));
        emit WorkflowTaskScheduled(wtid, workflowId, wf.workflowTaskQueue);
    }

    function claimNextWorkflowTask(bytes32 queue, uint32 leaseSec) external returns (uint256 workflowTaskId) {
        require(queue != bytes32(0), "VibeFlow: queue=0");
        require(workerAllowedOnQueue[msg.sender][queue], "VibeFlow: not allowed");
        if (leaseSec == 0) leaseSec = defaultTaskLeaseSec;

        uint256[] storage q = workflowTaskQueue[queue];
        uint256 i = workerCursorWorkflowTask[msg.sender][queue];

        for (; i < q.length; i++) {
            uint256 candidate = q[i];
            WorkflowTask storage wt = workflowTasks[candidate];
            if (wt.status == WorkflowTaskStatus.SCHEDULED) {
                _claimWorkflowTask(candidate, leaseSec);
                workerCursorWorkflowTask[msg.sender][queue] = i;
                return candidate;
            }
            if (wt.status == WorkflowTaskStatus.CLAIMED && block.timestamp > wt.leaseUntil) {
                // steal if lease expired
                _claimWorkflowTask(candidate, leaseSec);
                workerCursorWorkflowTask[msg.sender][queue] = i;
                return candidate;
            }
        }

        workerCursorWorkflowTask[msg.sender][queue] = q.length;
        return 0;
    }

    function claimWorkflowTask(uint256 workflowTaskId, uint32 leaseSec) external {
        WorkflowTask storage wt = workflowTasks[workflowTaskId];
        require(wt.status == WorkflowTaskStatus.SCHEDULED || wt.status == WorkflowTaskStatus.CLAIMED, "VibeFlow: not claimable");

        Workflow storage wf = workflows[wt.workflowId];
        require(workerAllowedOnQueue[msg.sender][wf.workflowTaskQueue], "VibeFlow: not allowed");

        if (leaseSec == 0) leaseSec = defaultTaskLeaseSec;
        _claimWorkflowTask(workflowTaskId, leaseSec);
    }

    function _claimWorkflowTask(uint256 workflowTaskId, uint32 leaseSec) internal {
        WorkflowTask storage wt = workflowTasks[workflowTaskId];

        if (wt.status == WorkflowTaskStatus.CLAIMED) {
            require(block.timestamp > wt.leaseUntil, "VibeFlow: lease active");
        }

        require(wt.status == WorkflowTaskStatus.SCHEDULED || wt.status == WorkflowTaskStatus.CLAIMED, "VibeFlow: bad status");
        require(block.timestamp <= wt.deadlineAt, "VibeFlow: WT scheduleToStart timeout");

        wt.status = WorkflowTaskStatus.CLAIMED;
        wt.assignedDecider = msg.sender;
        wt.startedAt = uint64(block.timestamp);
        wt.leaseUntil = uint64(block.timestamp + leaseSec);

        _appendHistory(wt.workflowId, HistoryEventType.WORKFLOW_TASK_STARTED, workflowTaskId, abi.encode(msg.sender, wt.leaseUntil, wt.expectedVersion, wt.fromHistoryIndex));
        emit WorkflowTaskClaimed(workflowTaskId, wt.workflowId, msg.sender, wt.leaseUntil);
    }

    function heartbeatWorkflowTask(uint256 workflowTaskId, uint32 extendSec) external {
        WorkflowTask storage wt = workflowTasks[workflowTaskId];
        require(wt.status == WorkflowTaskStatus.CLAIMED, "VibeFlow: not claimed");
        require(wt.assignedDecider == msg.sender, "VibeFlow: not assignee");
        require(block.timestamp <= wt.leaseUntil, "VibeFlow: lease expired");
        if (extendSec == 0) extendSec = defaultTaskLeaseSec;
        wt.leaseUntil = uint64(block.timestamp + extendSec);
    }

    /**
     * Complete a workflow task (the atomic commit boundary).
     *
     * This is where the decider submits commands that will be applied atomically:
     *  - append history events for commands
     *  - update workflow state snapshot
     *  - schedule activities / timers / child workflows
     *  - complete/fail/cancel/terminate workflow
     *  - trigger next workflow task if needed
     */
    function completeWorkflowTask(
        uint256 workflowTaskId,
        uint64 expectedVersion,
        bytes calldata newStateSnapshot,
        Command[] calldata commands
    ) external {
        WorkflowTask storage wt = workflowTasks[workflowTaskId];
        require(wt.status == WorkflowTaskStatus.CLAIMED, "VibeFlow: WT not claimed");
        require(wt.assignedDecider == msg.sender, "VibeFlow: not assignee");
        require(block.timestamp <= wt.leaseUntil, "VibeFlow: lease expired");

        uint256 workflowId = wt.workflowId;
        Workflow storage wf = workflows[workflowId];
        require(wf.status == WorkflowStatus.RUNNING, "VibeFlow: workflow not running");

        // Optimistic concurrency: must match both wt.expectedVersion and provided expectedVersion
        require(expectedVersion == wt.expectedVersion, "VibeFlow: expectedVersion mismatch");
        require(expectedVersion == wf.version, "VibeFlow: workflow version mismatch");

        // Mark WT completed
        wt.status = WorkflowTaskStatus.COMPLETED;

        // Apply state snapshot update
        wf.state = newStateSnapshot;
        wf.updatedAt = uint64(block.timestamp);

        // Record WT completed event
        _appendHistory(workflowId, HistoryEventType.WORKFLOW_TASK_COMPLETED, workflowTaskId, abi.encode(msg.sender, expectedVersion, newStateSnapshot, commands));
        emit WorkflowTaskCompleted(workflowTaskId, workflowId, wf.version + 1);

        // Apply commands (atomic with everything above)
        bool scheduledSomething = false;
        bool workflowEnded = false;

        for (uint256 i = 0; i < commands.length; i++) {
            (bool didSchedule, bool didEnd) = _applyCommand(workflowId, commands[i]);
            if (didSchedule) scheduledSomething = true;
            if (didEnd) workflowEnded = true;
        }

        // Advance workflow version (commit point)
        wf.version = wf.version + 1;

        // If workflow still running and there were external side effects recorded (activities/timers/child/etc),
        // we do NOT automatically schedule next WT here. Instead:
        //  - activities/timers/signals/child completion will schedule the next WT when they happen.
        // However, if the decider wants immediate continuation (pure workflow logic), they can do so by:
        //  - scheduling a 0-delay timer (not allowed by check) OR record marker + external signal
        // For convenience, if commands scheduled nothing and workflow not ended,
        // we schedule a new WT so the workflow can continue purely by decision steps.
        if (!workflowEnded && !scheduledSomething) {
            _scheduleWorkflowTask(workflowId, uint64(history[workflowId].length));
        }
    }

    // ------------------------------------------------------------
    // Activities: schedule/claim/start/heartbeat/complete/fail
    // ------------------------------------------------------------

    function claimNextActivity(bytes32 queue, uint32 leaseSec) external returns (uint256 activityId) {
        require(queue != bytes32(0), "VibeFlow: queue=0");
        require(workerAllowedOnQueue[msg.sender][queue], "VibeFlow: not allowed");
        if (leaseSec == 0) leaseSec = defaultTaskLeaseSec;

        uint256[] storage q = activityTaskQueue[queue];
        uint256 i = workerCursorActivityTask[msg.sender][queue];

        for (; i < q.length; i++) {
            uint256 candidate = q[i];
            Activity storage a = activities[candidate];

            if (a.status == ActivityStatus.SCHEDULED) {
                _claimActivity(candidate, leaseSec);
                workerCursorActivityTask[msg.sender][queue] = i;
                return candidate;
            }

            if (a.status == ActivityStatus.CLAIMED && block.timestamp > a.leaseUntil) {
                _claimActivity(candidate, leaseSec);
                workerCursorActivityTask[msg.sender][queue] = i;
                return candidate;
            }

            // retry-eligible activities re-enter SCHEDULED via retryActivity()
        }

        workerCursorActivityTask[msg.sender][queue] = q.length;
        return 0;
    }

    function claimActivity(uint256 activityId, uint32 leaseSec) external {
        Activity storage a = activities[activityId];
        require(a.status == ActivityStatus.SCHEDULED || a.status == ActivityStatus.CLAIMED, "VibeFlow: not claimable");
        require(workerAllowedOnQueue[msg.sender][a.taskQueue], "VibeFlow: not allowed");
        if (leaseSec == 0) leaseSec = defaultTaskLeaseSec;
        _claimActivity(activityId, leaseSec);
    }

    function _claimActivity(uint256 activityId, uint32 leaseSec) internal {
        Activity storage a = activities[activityId];
        Workflow storage wf = workflows[a.workflowId];
        require(wf.status == WorkflowStatus.RUNNING, "VibeFlow: workflow not running");

        if (a.status == ActivityStatus.CLAIMED) {
            require(block.timestamp > a.leaseUntil, "VibeFlow: lease active");
        }

        require(a.status == ActivityStatus.SCHEDULED || a.status == ActivityStatus.CLAIMED, "VibeFlow: bad status");

        // scheduleToStart timeout
        if (a.timeouts.scheduleToStartSec > 0) {
            require(block.timestamp <= a.scheduleToStartDeadlineAt, "VibeFlow: scheduleToStart timeout");
        }

        a.status = ActivityStatus.CLAIMED;
        a.assignedWorker = msg.sender;
        a.claimedAt = uint64(block.timestamp);
        a.leaseUntil = uint64(block.timestamp + leaseSec);

        _appendHistory(a.workflowId, HistoryEventType.ACTIVITY_TASK_CLAIMED, activityId, abi.encode(msg.sender, a.attempt, a.leaseUntil));
        emit ActivityClaimed(activityId, a.workflowId, msg.sender, a.leaseUntil);
    }

    function startActivity(uint256 activityId) external {
        Activity storage a = activities[activityId];
        require(a.status == ActivityStatus.CLAIMED, "VibeFlow: not claimed");
        require(a.assignedWorker == msg.sender, "VibeFlow: not assignee");
        require(block.timestamp <= a.leaseUntil, "VibeFlow: lease expired");

        Workflow storage wf = workflows[a.workflowId];
        require(wf.status == WorkflowStatus.RUNNING, "VibeFlow: workflow not running");

        // If cancel requested before start, respect it
        require(!a.cancelRequested, "VibeFlow: cancel requested");

        a.status = ActivityStatus.STARTED;
        a.startedAt = uint64(block.timestamp);

        // startToClose timeout
        if (a.timeouts.startToCloseSec > 0) {
            a.startToCloseDeadlineAt = uint64(block.timestamp + a.timeouts.startToCloseSec);
        }

        // heartbeat timeout
        if (a.timeouts.heartbeatTimeoutSec > 0) {
            a.lastHeartbeatAt = uint64(block.timestamp);
            a.heartbeatDeadlineAt = uint64(block.timestamp + a.timeouts.heartbeatTimeoutSec);
        }

        _appendHistory(a.workflowId, HistoryEventType.ACTIVITY_STARTED, activityId, abi.encode(msg.sender, a.attempt));
        emit ActivityStarted(activityId, a.workflowId, msg.sender);
    }

    function heartbeatActivity(uint256 activityId, bytes calldata details, uint32 extendLeaseSec) external {
        Activity storage a = activities[activityId];
        require(a.status == ActivityStatus.STARTED || a.status == ActivityStatus.CLAIMED, "VibeFlow: bad status");
        require(a.assignedWorker == msg.sender, "VibeFlow: not assignee");
        require(block.timestamp <= a.leaseUntil, "VibeFlow: lease expired");

        // update heartbeat deadlines (only meaningful in STARTED)
        if (a.status == ActivityStatus.STARTED && a.timeouts.heartbeatTimeoutSec > 0) {
            a.lastHeartbeatAt = uint64(block.timestamp);
            a.heartbeatDeadlineAt = uint64(block.timestamp + a.timeouts.heartbeatTimeoutSec);
        }

        if (extendLeaseSec > 0) {
            a.leaseUntil = uint64(block.timestamp + extendLeaseSec);
        }

        _appendHistory(a.workflowId, HistoryEventType.ACTIVITY_HEARTBEAT, activityId, abi.encode(msg.sender, details));
    }

    function completeActivity(uint256 activityId, bytes calldata result) external {
        Activity storage a = activities[activityId];
        require(a.status == ActivityStatus.STARTED, "VibeFlow: not started");
        require(a.assignedWorker == msg.sender, "VibeFlow: not assignee");
        require(block.timestamp <= a.leaseUntil, "VibeFlow: lease expired");

        Workflow storage wf = workflows[a.workflowId];
        require(wf.status == WorkflowStatus.RUNNING, "VibeFlow: workflow not running");
        require(!a.cancelRequested, "VibeFlow: cancel requested");

        // If startToClose exceeded, treat as timeout
        if (a.timeouts.startToCloseSec > 0 && block.timestamp > a.startToCloseDeadlineAt) {
            _timeoutActivity(activityId, "START_TO_CLOSE_TIMEOUT");
            return;
        }

        a.status = ActivityStatus.SUCCEEDED;
        a.result = result;

        // release lease
        a.assignedWorker = address(0);
        a.leaseUntil = 0;

        _appendHistory(a.workflowId, HistoryEventType.ACTIVITY_COMPLETED, activityId, abi.encode(result));
        emit ActivityCompleted(activityId, a.workflowId);

        // Trigger next workflow task (Temporal: activity completion creates a new workflow task)
        _scheduleWorkflowTask(a.workflowId, uint64(history[a.workflowId].length) - 1);
    }

    function failActivity(uint256 activityId, bytes calldata failure) external {
        Activity storage a = activities[activityId];
        require(a.status == ActivityStatus.STARTED || a.status == ActivityStatus.CLAIMED, "VibeFlow: bad status");
        require(a.assignedWorker == msg.sender, "VibeFlow: not assignee");
        require(block.timestamp <= a.leaseUntil, "VibeFlow: lease expired");

        Workflow storage wf = workflows[a.workflowId];
        require(wf.status == WorkflowStatus.RUNNING, "VibeFlow: workflow not running");

        // If cancel requested, convert to canceled
        if (a.cancelRequested) {
            _cancelActivityInternal(activityId, "CANCEL_REQUESTED");
            return;
        }

        a.failure = failure;
        (bool willRetry, uint64 nextRetryAt) = _applyRetryOrFail(activityId, /*isTimeout*/ false, failure);

        emit ActivityFailed(activityId, a.workflowId, willRetry, nextRetryAt);

        // Trigger workflow task (Temporal: activity failed produces event, then workflow task)
        _scheduleWorkflowTask(a.workflowId, uint64(history[a.workflowId].length) - 1);
    }

    // ------------------------------------------------------------
    // Timers
    // ------------------------------------------------------------

    function fireTimer(uint256 timerId) external {
        Timer storage t = timers[timerId];
        require(t.open, "VibeFlow: timer closed");
        require(block.timestamp >= t.fireAt, "VibeFlow: not ready");

        Workflow storage wf = workflows[t.workflowId];
        require(wf.status == WorkflowStatus.RUNNING, "VibeFlow: workflow not running");

        t.open = false;

        _appendHistory(t.workflowId, HistoryEventType.TIMER_FIRED, timerId, abi.encode(t.payload));
        emit TimerFired(timerId, t.workflowId);

        _scheduleWorkflowTask(t.workflowId, uint64(history[t.workflowId].length) - 1);
    }

    // ------------------------------------------------------------
    // Timeouts / scanners (anyone can call)
    // ------------------------------------------------------------

    function tickWorkflowTaskTimeout(uint256 workflowTaskId) external {
        WorkflowTask storage wt = workflowTasks[workflowTaskId];
        if (wt.status == WorkflowTaskStatus.SCHEDULED && block.timestamp > wt.deadlineAt) {
            wt.status = WorkflowTaskStatus.TIMED_OUT;
            _appendHistory(wt.workflowId, HistoryEventType.WORKFLOW_TASK_COMPLETED, workflowTaskId, abi.encode("WORKFLOW_TASK_TIMED_OUT"));
            // schedule a new workflow task so decider can continue
            _scheduleWorkflowTask(wt.workflowId, uint64(history[wt.workflowId].length) - 1);
        }
        // If CLAIMED and lease expired: reclaim via claimNext/claim
    }

    function tickActivityTimeout(uint256 activityId) external {
        Activity storage a = activities[activityId];
        Workflow storage wf = workflows[a.workflowId];
        require(wf.status == WorkflowStatus.RUNNING, "VibeFlow: workflow not running");

        // scheduleToStart timeout
        if (a.status == ActivityStatus.SCHEDULED && a.timeouts.scheduleToStartSec > 0 && block.timestamp > a.scheduleToStartDeadlineAt) {
            _timeoutActivity(activityId, "SCHEDULE_TO_START_TIMEOUT");
            _scheduleWorkflowTask(a.workflowId, uint64(history[a.workflowId].length) - 1);
            return;
        }

        // startToClose timeout
        if (a.status == ActivityStatus.STARTED && a.timeouts.startToCloseSec > 0 && block.timestamp > a.startToCloseDeadlineAt) {
            _timeoutActivity(activityId, "START_TO_CLOSE_TIMEOUT");
            _scheduleWorkflowTask(a.workflowId, uint64(history[a.workflowId].length) - 1);
            return;
        }

        // heartbeat timeout
        if (a.status == ActivityStatus.STARTED && a.timeouts.heartbeatTimeoutSec > 0 && block.timestamp > a.heartbeatDeadlineAt) {
            _timeoutActivity(activityId, "HEARTBEAT_TIMEOUT");
            _scheduleWorkflowTask(a.workflowId, uint64(history[a.workflowId].length) - 1);
            return;
        }
    }

    function retryActivity(uint256 activityId) external {
        Activity storage a = activities[activityId];
        Workflow storage wf = workflows[a.workflowId];
        require(wf.status == WorkflowStatus.RUNNING, "VibeFlow: workflow not running");
        require(a.status == ActivityStatus.FAILED || a.status == ActivityStatus.TIMED_OUT, "VibeFlow: not retryable");
        require(a.nextRetryAt != 0 && block.timestamp >= a.nextRetryAt, "VibeFlow: not ready");

        // schedule again
        a.status = ActivityStatus.SCHEDULED;
        a.assignedWorker = address(0);
        a.leaseUntil = 0;

        a.scheduledAt = uint64(block.timestamp);
        if (a.timeouts.scheduleToStartSec > 0) {
            a.scheduleToStartDeadlineAt = uint64(block.timestamp + a.timeouts.scheduleToStartSec);
        }

        a.failure = "";
        a.result = "";
        a.cancelRequested = false;

        // push back into its queue (append-only, but that's fine)
        activityTaskQueue[a.taskQueue].push(activityId);

        _appendHistory(a.workflowId, HistoryEventType.ACTIVITY_SCHEDULED, activityId, abi.encode(a.activityType, a.taskQueue, a.input, a.attempt));
        emit ActivityScheduled(activityId, a.workflowId, a.activityType, a.taskQueue, a.attempt);
    }

    // ------------------------------------------------------------
    // Workflow termination APIs (owner)
    // ------------------------------------------------------------

    function cancelWorkflow(uint256 workflowId, bytes calldata reason) external {
        Workflow storage wf = workflows[workflowId];
        require(wf.owner == msg.sender, "VibeFlow: not owner");
        require(wf.status == WorkflowStatus.RUNNING, "VibeFlow: not running");

        wf.status = WorkflowStatus.CANCELED;
        wf.result = reason;
        wf.updatedAt = uint64(block.timestamp);

        _appendHistory(workflowId, HistoryEventType.WORKFLOW_CANCELED, 0, abi.encode(reason));
        emit WorkflowCanceled(workflowId);
    }

    function terminateWorkflow(uint256 workflowId, bytes calldata reason) external {
        Workflow storage wf = workflows[workflowId];
        require(wf.owner == msg.sender || msg.sender == admin, "VibeFlow: not allowed");
        require(wf.status == WorkflowStatus.RUNNING, "VibeFlow: not running");

        wf.status = WorkflowStatus.TERMINATED;
        wf.result = reason;
        wf.updatedAt = uint64(block.timestamp);

        _appendHistory(workflowId, HistoryEventType.WORKFLOW_TERMINATED, 0, abi.encode(reason));
        emit WorkflowTerminated(workflowId);
    }

    // ------------------------------------------------------------
    // Command application (decider-driven)
    // ------------------------------------------------------------

    function _applyCommand(uint256 workflowId, Command calldata c) internal returns (bool scheduledSomething, bool workflowEnded) {
        if (c.typ == CommandType.SCHEDULE_ACTIVITY) {
            // payload: (bytes32 activityType, bytes32 taskQueue, bytes input, RetryPolicy retry, ActivityTimeouts timeouts)
            (bytes32 activityType, bytes32 taskQueueName, bytes memory input, RetryPolicy memory rp, ActivityTimeouts memory to) =
                abi.decode(c.payload, (bytes32, bytes32, bytes, RetryPolicy, ActivityTimeouts));
            uint256 aid = _scheduleActivity(workflowId, activityType, taskQueueName, input, rp, to);
            scheduledSomething = true;
            return (scheduledSomething, false);
        }

        if (c.typ == CommandType.START_TIMER) {
            // payload: (uint64 fireAt, bytes payload)
            (uint64 fireAt, bytes memory payload) = abi.decode(c.payload, (uint64, bytes));
            uint256 tid = _scheduleTimer(workflowId, fireAt, payload);
            scheduledSomething = true;
            return (scheduledSomething, false);
        }

        if (c.typ == CommandType.COMPLETE_WORKFLOW) {
            // payload: (bytes result)
            bytes memory result = abi.decode(c.payload, (bytes));
            _completeWorkflowInternal(workflowId, result);
            return (false, true);
        }

        if (c.typ == CommandType.FAIL_WORKFLOW) {
            // payload: (bytes failure)
            bytes memory failure = abi.decode(c.payload, (bytes));
            _failWorkflowInternal(workflowId, failure);
            return (false, true);
        }

        if (c.typ == CommandType.CANCEL_WORKFLOW) {
            // payload: (bytes reason)
            bytes memory reason = abi.decode(c.payload, (bytes));
            _cancelWorkflowInternal(workflowId, reason);
            return (false, true);
        }

        if (c.typ == CommandType.TERMINATE_WORKFLOW) {
            bytes memory reason = abi.decode(c.payload, (bytes));
            _terminateWorkflowInternal(workflowId, reason);
            return (false, true);
        }

        if (c.typ == CommandType.CANCEL_ACTIVITY) {
            // payload: (uint256 activityId, bytes reason)
            (uint256 activityId, bytes memory reason) = abi.decode(c.payload, (uint256, bytes));
            _requestCancelActivity(workflowId, activityId, reason);
            return (false, false);
        }

        if (c.typ == CommandType.RECORD_MARKER) {
            // payload: (bytes32 markerName, bytes markerData)
            (bytes32 markerName, bytes memory markerData) = abi.decode(c.payload, (bytes32, bytes));
            _appendHistory(workflowId, HistoryEventType.MARKER_RECORDED, 0, abi.encode(markerName, markerData));
            return (false, false);
        }

        if (c.typ == CommandType.UPSERT_SEARCH_ATTRIBUTES) {
            // payload: (bytes32[] keys, bytes[] values)
            (bytes32[] memory keys, bytes[] memory values) = abi.decode(c.payload, (bytes32[], bytes[]));
            require(keys.length == values.length, "VibeFlow: upsert len mismatch");
            Workflow storage wf = workflows[workflowId];
            for (uint256 i = 0; i < keys.length; i++) {
                _upsertSearchAttr(wf, keys[i], values[i]);
            }
            _appendHistory(workflowId, HistoryEventType.SEARCH_ATTRIBUTES_UPSERTED, 0, abi.encode(keys, values));
            return (false, false);
        }

        if (c.typ == CommandType.REQUEST_CANCEL_EXTERNAL_WORKFLOW) {
            // payload: (uint256 externalWorkflowId, bytes reason)
            (uint256 externalWorkflowId, bytes memory reason) = abi.decode(c.payload, (uint256, bytes));
            _appendHistory(workflowId, HistoryEventType.REQUEST_CANCEL_EXTERNAL_WORKFLOW, externalWorkflowId, abi.encode(reason));
            // optionally also set a cancel flag on external workflow if allowed by policy:
            // Here we DO NOT automatically cancel external workflow (permission concerns).
            return (false, false);
        }

        if (c.typ == CommandType.START_CHILD_WORKFLOW) {
            // payload: (bytes32 workflowType, bytes32 workflowTaskQueue, bytes input, bytes initialState)
            (bytes32 wtype, bytes32 wtq, bytes memory input, bytes memory initialState) =
                abi.decode(c.payload, (bytes32, bytes32, bytes, bytes));

            uint256 childId = _startChildWorkflow(workflowId, wtype, wtq, input, initialState);
            scheduledSomething = true;
            return (scheduledSomething, false);
        }

        revert("VibeFlow: unknown command");
    }

    // ------------------------------------------------------------
    // Internals: workflow completion/fail/cancel/terminate
    // ------------------------------------------------------------

    function _completeWorkflowInternal(uint256 workflowId, bytes memory result) internal {
        Workflow storage wf = workflows[workflowId];
        require(wf.status == WorkflowStatus.RUNNING, "VibeFlow: not running");
        wf.status = WorkflowStatus.COMPLETED;
        wf.result = result;
        wf.updatedAt = uint64(block.timestamp);
        _appendHistory(workflowId, HistoryEventType.WORKFLOW_COMPLETED, 0, abi.encode(result));
        emit WorkflowCompleted(workflowId);

        _notifyParentIfChild(workflowId, /*completed*/ true, result);
    }

    function _failWorkflowInternal(uint256 workflowId, bytes memory failure) internal {
        Workflow storage wf = workflows[workflowId];
        require(wf.status == WorkflowStatus.RUNNING, "VibeFlow: not running");
        wf.status = WorkflowStatus.FAILED;
        wf.result = failure;
        wf.updatedAt = uint64(block.timestamp);
        _appendHistory(workflowId, HistoryEventType.WORKFLOW_FAILED, 0, abi.encode(failure));
        emit WorkflowFailed(workflowId);

        _notifyParentIfChild(workflowId, /*completed*/ false, failure);
    }

    function _cancelWorkflowInternal(uint256 workflowId, bytes memory reason) internal {
        Workflow storage wf = workflows[workflowId];
        require(wf.status == WorkflowStatus.RUNNING, "VibeFlow: not running");
        wf.status = WorkflowStatus.CANCELED;
        wf.result = reason;
        wf.updatedAt = uint64(block.timestamp);
        _appendHistory(workflowId, HistoryEventType.WORKFLOW_CANCELED, 0, abi.encode(reason));
        emit WorkflowCanceled(workflowId);

        _notifyParentIfChild(workflowId, /*completed*/ false, reason);
    }

    function _terminateWorkflowInternal(uint256 workflowId, bytes memory reason) internal {
        Workflow storage wf = workflows[workflowId];
        require(wf.status == WorkflowStatus.RUNNING, "VibeFlow: not running");
        wf.status = WorkflowStatus.TERMINATED;
        wf.result = reason;
        wf.updatedAt = uint64(block.timestamp);
        _appendHistory(workflowId, HistoryEventType.WORKFLOW_TERMINATED, 0, abi.encode(reason));
        emit WorkflowTerminated(workflowId);

        _notifyParentIfChild(workflowId, /*completed*/ false, reason);
    }

    // ------------------------------------------------------------
    // Internals: child workflows
    // ------------------------------------------------------------

    function _startChildWorkflow(
        uint256 parentWorkflowId,
        bytes32 workflowType,
        bytes32 workflowTaskQueueName,
        bytes memory input,
        bytes memory initialState
    ) internal returns (uint256 childWorkflowId) {
        Workflow storage parent = workflows[parentWorkflowId];
        require(parent.status == WorkflowStatus.RUNNING, "VibeFlow: parent not running");
        require(workflowType != bytes32(0), "VibeFlow: child type=0");
        require(workflowTaskQueueName != bytes32(0), "VibeFlow: child queue=0");

        childWorkflowId = nextWorkflowId++;
        uint256 parentChildId = workflowChildren[parentWorkflowId].length + 1;

        Workflow storage child = workflows[childWorkflowId];
        child.id = childWorkflowId;
        child.parentWorkflowId = parentWorkflowId;
        child.parentChildId = parentChildId;
        child.owner = parent.owner; // inherit ownership policy (tune as needed)
        child.status = WorkflowStatus.RUNNING;
        child.workflowType = workflowType;
        child.workflowTaskQueue = workflowTaskQueueName;
        child.input = input;
        child.state = initialState;
        child.version = 0;
        child.createdAt = uint64(block.timestamp);
        child.updatedAt = uint64(block.timestamp);

        workflowChildren[parentWorkflowId].push(childWorkflowId);

        _appendHistory(parentWorkflowId, HistoryEventType.CHILD_WORKFLOW_STARTED, parentChildId, abi.encode(childWorkflowId, workflowType, workflowTaskQueueName, input, initialState));
        emit ChildWorkflowStarted(parentWorkflowId, childWorkflowId, parentChildId);

        _appendHistory(childWorkflowId, HistoryEventType.WORKFLOW_STARTED, 0, abi.encode(workflowType, workflowTaskQueueName, input, initialState));
        emit WorkflowStarted(childWorkflowId, workflowType, workflowTaskQueueName);

        _scheduleWorkflowTask(childWorkflowId, 0);
    }

    function _notifyParentIfChild(uint256 childWorkflowId, bool completed, bytes memory payload) internal {
        Workflow storage child = workflows[childWorkflowId];
        if (child.parentWorkflowId == 0) return;

        uint256 parentId = child.parentWorkflowId;
        Workflow storage parent = workflows[parentId];
        if (parent.status != WorkflowStatus.RUNNING) return;

        if (child.status == WorkflowStatus.COMPLETED) {
            _appendHistory(parentId, HistoryEventType.CHILD_WORKFLOW_COMPLETED, child.parentChildId, abi.encode(childWorkflowId, payload));
            emit ChildWorkflowCompleted(parentId, childWorkflowId);
        } else if (child.status == WorkflowStatus.FAILED) {
            _appendHistory(parentId, HistoryEventType.CHILD_WORKFLOW_FAILED, child.parentChildId, abi.encode(childWorkflowId, payload));
            emit ChildWorkflowFailed(parentId, childWorkflowId);
        } else if (child.status == WorkflowStatus.CANCELED) {
            _appendHistory(parentId, HistoryEventType.CHILD_WORKFLOW_CANCELED, child.parentChildId, abi.encode(childWorkflowId, payload));
            emit ChildWorkflowCanceled(parentId, childWorkflowId);
        } else {
            // terminated also treated as failed-like
            _appendHistory(parentId, HistoryEventType.CHILD_WORKFLOW_FAILED, child.parentChildId, abi.encode(childWorkflowId, payload));
            emit ChildWorkflowFailed(parentId, childWorkflowId);
        }

        // Parent gets a new workflow task
        _scheduleWorkflowTask(parentId, uint64(history[parentId].length) - 1);

        completed; // silence warning (kept for readability)
    }

    // ------------------------------------------------------------
    // Internals: schedule activity + timer
    // ------------------------------------------------------------

    function _scheduleActivity(
        uint256 workflowId,
        bytes32 activityType,
        bytes32 taskQueueName,
        bytes memory input,
        RetryPolicy memory rp,
        ActivityTimeouts memory to
    ) internal returns (uint256 activityId) {
        Workflow storage wf = workflows[workflowId];
        require(wf.status == WorkflowStatus.RUNNING, "VibeFlow: workflow not running");
        require(activityType != bytes32(0), "VibeFlow: activityType=0");
        require(taskQueueName != bytes32(0), "VibeFlow: taskQueue=0");

        activityId = nextActivityId++;

        Activity storage a = activities[activityId];
        a.id = activityId;
        a.workflowId = workflowId;
        a.activityType = activityType;
        a.taskQueue = taskQueueName;
        a.status = ActivityStatus.SCHEDULED;
        a.input = input;

        // normalize retry
        if (!rp.enabled) {
            // retries disabled
            a.retry = rp;
            a.maxAttempts = 1;
        } else {
            a.retry = rp.enabled ? rp : defaultRetry;
            if (a.retry.maxAttempts == 0) a.retry.maxAttempts = defaultRetry.maxAttempts;
            if (a.retry.initialIntervalSec == 0) a.retry.initialIntervalSec = defaultRetry.initialIntervalSec;
            if (a.retry.backoffMultiplierBP == 0) a.retry.backoffMultiplierBP = defaultRetry.backoffMultiplierBP;
            if (a.retry.maxIntervalSec == 0) a.retry.maxIntervalSec = defaultRetry.maxIntervalSec;
            a.maxAttempts = a.retry.maxAttempts;
        }

        // normalize timeouts
        ActivityTimeouts memory nto = to;
        if (nto.scheduleToStartSec == 0) nto.scheduleToStartSec = defaultActivityTimeouts.scheduleToStartSec;
        if (nto.startToCloseSec == 0) nto.startToCloseSec = defaultActivityTimeouts.startToCloseSec;
        if (nto.heartbeatTimeoutSec == 0) nto.heartbeatTimeoutSec = defaultActivityTimeouts.heartbeatTimeoutSec;
        a.timeouts = nto;

        a.attempt = 1;
        a.scheduledAt = uint64(block.timestamp);

        if (a.timeouts.scheduleToStartSec > 0) {
            a.scheduleToStartDeadlineAt = uint64(block.timestamp + a.timeouts.scheduleToStartSec);
        }

        workflowActivities[workflowId].push(activityId);
        activityTaskQueue[taskQueueName].push(activityId);

        _appendHistory(workflowId, HistoryEventType.ACTIVITY_SCHEDULED, activityId, abi.encode(activityType, taskQueueName, input, a.attempt, a.retry, a.timeouts));
        emit ActivityScheduled(activityId, workflowId, activityType, taskQueueName, a.attempt);
    }

    function _scheduleTimer(uint256 workflowId, uint64 fireAt, bytes memory payload) internal returns (uint256 timerId) {
        Workflow storage wf = workflows[workflowId];
        require(wf.status == WorkflowStatus.RUNNING, "VibeFlow: workflow not running");
        require(fireAt > block.timestamp, "VibeFlow: fireAt must be future");

        timerId = nextTimerId++;
        Timer storage t = timers[timerId];
        t.id = timerId;
        t.workflowId = workflowId;
        t.open = true;
        t.fireAt = fireAt;
        t.payload = payload;

        workflowTimers[workflowId].push(timerId);

        _appendHistory(workflowId, HistoryEventType.TIMER_SCHEDULED, timerId, abi.encode(fireAt, payload));
        emit TimerScheduled(timerId, workflowId, fireAt);
    }

    // ------------------------------------------------------------
    // Cancellation
    // ------------------------------------------------------------

    function _requestCancelActivity(uint256 workflowId, uint256 activityId, bytes memory reason) internal {
        Activity storage a = activities[activityId];
        require(a.workflowId == workflowId, "VibeFlow: activity not in workflow");
        require(a.status != ActivityStatus.SUCCEEDED && a.status != ActivityStatus.FAILED && a.status != ActivityStatus.TIMED_OUT && a.status != ActivityStatus.CANCELED, "VibeFlow: activity closed");

        a.cancelRequested = true;
        _appendHistory(workflowId, HistoryEventType.ACTIVITY_CANCELED, activityId, abi.encode("CANCEL_REQUESTED", reason));

        // If not started, cancel immediately (like Temporal's cancel before start)
        if (a.status == ActivityStatus.SCHEDULED || a.status == ActivityStatus.CLAIMED) {
            _cancelActivityInternal(activityId, reason);
        }
    }

    function _cancelActivityInternal(uint256 activityId, bytes memory reason) internal {
        Activity storage a = activities[activityId];
        if (a.status == ActivityStatus.CANCELED) return;

        a.status = ActivityStatus.CANCELED;
        a.failure = reason;
        a.assignedWorker = address(0);
        a.leaseUntil = 0;

        _appendHistory(a.workflowId, HistoryEventType.ACTIVITY_CANCELED, activityId, abi.encode(reason));
        emit ActivityCanceled(activityId, a.workflowId);

        _scheduleWorkflowTask(a.workflowId, uint64(history[a.workflowId].length) - 1);
    }

    // ------------------------------------------------------------
    // Timeouts + retries internals
    // ------------------------------------------------------------

    function _timeoutActivity(uint256 activityId, bytes memory reason) internal {
        Activity storage a = activities[activityId];
        if (a.status == ActivityStatus.SUCCEEDED || a.status == ActivityStatus.CANCELED) return;

        // Mark timed out and apply retry if any
        (bool willRetry, uint64 nextRetryAt) = _applyRetryOrFail(activityId, /*isTimeout*/ true, reason);
        emit ActivityTimedOut(activityId, a.workflowId, willRetry, nextRetryAt);
    }

    function _applyRetryOrFail(uint256 activityId, bool isTimeout, bytes memory details)
        internal
        returns (bool willRetry, uint64 nextRetryAt)
    {
        Activity storage a = activities[activityId];

        // release worker assignment on failure/timeout
        a.assignedWorker = address(0);
        a.leaseUntil = 0;

        if (isTimeout) {
            a.status = ActivityStatus.TIMED_OUT;
            _appendHistory(a.workflowId, HistoryEventType.ACTIVITY_TIMED_OUT, activityId, abi.encode(details, a.attempt));
        } else {
            a.status = ActivityStatus.FAILED;
            _appendHistory(a.workflowId, HistoryEventType.ACTIVITY_FAILED, activityId, abi.encode(details, a.attempt));
        }

        // no retry configured
        if (!a.retry.enabled || a.maxAttempts <= 1) {
            a.nextRetryAt = 0;
            return (false, 0);
        }

        if (a.attempt >= a.maxAttempts) {
            a.nextRetryAt = 0;
            return (false, 0);
        }

        // compute backoff delay based on attemptJustFailed = a.attempt
        uint32 delay = _backoffDelay(a.retry, a.attempt);
        nextRetryAt = uint64(block.timestamp + delay);
        a.nextRetryAt = nextRetryAt;

        // increment attempt for the next scheduling
        a.attempt += 1;

        willRetry = true;
    }

    function _backoffDelay(RetryPolicy memory rp, uint8 attemptJustFailed) internal pure returns (uint32) {
        // attemptJustFailed=1 => next attempt=2 => exponent 0
        uint8 exp = attemptJustFailed > 1 ? attemptJustFailed - 1 : 0;

        uint256 delay = rp.initialIntervalSec;
        for (uint8 i = 0; i < exp; i++) {
            delay = (delay * rp.backoffMultiplierBP) / 10000;
            if (delay > rp.maxIntervalSec) {
                delay = rp.maxIntervalSec;
                break;
            }
        }
        if (delay > rp.maxIntervalSec) delay = rp.maxIntervalSec;
        return uint32(delay);
    }

    // ------------------------------------------------------------
    // Search attributes internal
    // ------------------------------------------------------------

    function _upsertSearchAttr(Workflow storage wf, bytes32 key, bytes memory value) internal {
        require(key != bytes32(0), "VibeFlow: key=0");
        wf.searchAttr[key] = value;
        if (!wf.searchAttrKeyExists[key]) {
            wf.searchAttrKeyExists[key] = true;
            wf.searchAttrKeys.push(key);
        }
    }

    // ------------------------------------------------------------
    // History internal
    // ------------------------------------------------------------

    function _appendHistory(uint256 workflowId, HistoryEventType typ, uint256 refId, bytes memory data) internal {
        history[workflowId].push(HistoryEvent({
            ts: uint64(block.timestamp),
            typ: typ,
            refId: refId,
            data: data
        }));
        workflows[workflowId].historyLen = uint64(history[workflowId].length);
        workflows[workflowId].updatedAt = uint64(block.timestamp);
    }

    // ------------------------------------------------------------
    // Convenience list helpers
    // ------------------------------------------------------------

    function listWorkflowTasks(uint256 workflowId) external view returns (uint256[] memory) {
        return workflowWorkflowTasks[workflowId];
    }

    function listActivities(uint256 workflowId) external view returns (uint256[] memory) {
        return workflowActivities[workflowId];
    }

    function listTimers(uint256 workflowId) external view returns (uint256[] memory) {
        return workflowTimers[workflowId];
    }

    function listChildren(uint256 workflowId) external view returns (uint256[] memory) {
        return workflowChildren[workflowId];
    }

    function workflowTaskQueueLength(bytes32 queue) external view returns (uint256) {
        return workflowTaskQueue[queue].length;
    }

    function activityTaskQueueLength(bytes32 queue) external view returns (uint256) {
        return activityTaskQueue[queue].length;
    }

    function workflowTaskQueueAt(bytes32 queue, uint256 idx) external view returns (uint256) {
        return workflowTaskQueue[queue][idx];
    }

    function activityTaskQueueAt(bytes32 queue, uint256 idx) external view returns (uint256) {
        return activityTaskQueue[queue][idx];
    }
}
