"""Deprecated: Generic RunPod job polling removed. Use Modal FunctionCall instead."""

def poll_job(*args, **kwargs):
    raise NotImplementedError("RunPod removed. Use modal.FunctionCall.from_id().get()")
