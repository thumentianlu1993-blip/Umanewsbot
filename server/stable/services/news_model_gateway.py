"""P01 固定模型任务的金额预约与单次调用边界。"""


class RequestDenied(ValueError):
    pass


def reserve_request(attempt_id, payload):
    # 在正式配置和额度实现前，默认拒绝所有外部请求。
    raise RequestDenied("not_configured")
