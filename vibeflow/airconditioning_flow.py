from eth_abi import encode
from web3 import Web3

vf = w3.eth.contract(address=VIBEFLOW_ADDRESS, abi=VIBEFLOW_ABI)

admin = ADMIN_ADDRsensor = SENSOR_ADDRai_agent = AI_AGENT_ADDRhvac_agent = HVAC_AGENT_ADDRAI_DECIDER_Q = Web3.keccak(text="AI_DECIDER_Q")
HVAC_WORKER_Q = Web3.keccak(text="HVAC_WORKER_Q")
WF_TYPE = Web3.keccak(text="TEMP_CONTROL")
SIG_TEMP_READING = Web3.keccak(text="TEMP_READING")
ACT_SWITCH_AC_ON = Web3.keccak(text="SWITCH_AC_ON")
THRESHOLD_C =27#1) Admin grants queue permissionsvf.functions.setWorkerQueuePermission(ai_agent, AI_DECIDER_Q, True).transact({"from": admin})
vf.functions.setWorkerQueuePermission(hvac_agent, HVAC_WORKER_Q, True).transact({"from": admin})

#2) Start workflowtx = vf.functions.startWorkflow(
 WF_TYPE,
 AI_DECIDER_Q,
 b"{}",
 b'{"ac_on":false}',
 [],
 []
).transact({"from": sensor})
# parse WorkflowStarted event => workflow_idworkflow_id = parse_workflow_id(tx)

#3) Sensor pushes reading (e.g.,30.5C)
temp_c =30_50 # fixed-point,30.50Csig_data = encode(["int32"], [temp_c])
vf.functions.signalWorkflow(workflow_id, SIG_TEMP_READING, sig_data).transact({"from": sensor})

#4) AI agent claims workflow task and decideswt_id = vf.functions.claimNextWorkflowTask(AI_DECIDER_Q,60).call({"from": ai_agent})
vf.functions.claimNextWorkflowTask(AI_DECIDER_Q,60).transact({"from": ai_agent})

# Build Command[] with one SCHEDULE_ACTIVITY command if temp > threshold# CommandType.SCHEDULE_ACTIVITY ==0 in this contractretry = (True,5,10,20000,3600) # RetryPolicytimeouts = (300,300,60) # ActivityTimeoutsactivity_payload = encode(
 ["bytes32", "bytes32", "bytes", "(bool,uint8,uint32,uint32,uint32)", "(uint32,uint32,uint32)"],
 [ACT_SWITCH_AC_ON, HVAC_WORKER_Q, encode(["bool"], [True]), retry, timeouts]
)
commands = [(0, activity_payload)] # [(typ, payload)]

wf_task = vf.functions.workflowTasks(wt_id).call()
expected_version = wf_task[8] # expectedVersion fieldnew_state = b'{"ac_on_pending":true}'

vf.functions.completeWorkflowTask(
 wt_id,
 expected_version,
 new_state,
 commands).transact({"from": ai_agent})

#5) HVAC agent executes activityact_id = vf.functions.claimNextActivity(HVAC_WORKER_Q,60).call({"from": hvac_agent})
vf.functions.claimNextActivity(HVAC_WORKER_Q,60).transact({"from": hvac_agent})
vf.functions.startActivity(act_id).transact({"from": hvac_agent})

# Off-chain side effect: switch AC relay ON, then report success on-chainvf.functions.completeActivity(act_id, b'{"ac":"on"}').transact({"from": hvac_agent})

#6) AI agent gets follow-up workflow task and finalizes state/workflowwt2_id = vf.functions.claimNextWorkflowTask(AI_DECIDER_Q,60).call({"from": ai_agent})
vf.functions.claimNextWorkflowTask(AI_DECIDER_Q,60).transact({"from": ai_agent})
wf_task2 = vf.functions.workflowTasks(wt2_id).call()
expected_version2 = wf_task2[8]

# CommandType.COMPLETE_WORKFLOW ==2complete_payload = encode(["bytes"], [b'{"status":"done","ac_on":true}'])
commands2 = [(2, complete_payload)]

vf.functions.completeWorkflowTask(
 wt2_id,
 expected_version2,
 b'{"ac_on":true}',
 commands2).transact({"from": ai_agent})
