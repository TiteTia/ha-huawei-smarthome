"""User-contributed protocol for Huawei product 105H (BroadLink 智能排插 MP1-1K3S2U-TL).

设备类型: 智能插排 (MultiSocket)
制造商: 杭州古北电子科技有限公司 (BroadLink), 型号 MP1-1K3S2U-TL
核心服务:
   switch.on   bool RW 总开关
   switchN.on  bool RW (N=1..N) 分路开关

CDN Profile 声明 switch/switch1..switch3 共 4 路, 但真机运行时状态
实报还包含 switch4 (推测为 USB 口控制), 共 5 路。

本适配器按设备实际存在的服务动态生成 HA ``switch``, 不写死路数。
开关命令沿用统一格式, 已在真实设备（总开关 + 4 分路, 共 5 路）实测验证。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_SWITCH_SERVICES = [
    ("switch", "总开关"),
    ("switch1", "开关1"),
    ("switch2", "开关2"),
    ("switch3", "开关3"),
    ("switch4", "开关4"),
]


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.casefold() in {"1", "true", "on"}:
            return True
        if value.casefold() in {"0", "false", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


class Product105HAdapter:
    """105H BroadLink 4路智能排插适配器。"""

    prod_id = "105H"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None:
            return ()

        def _switch_spec(sid: str, label: str) -> EntitySpec:
            def state(device: DeviceContext) -> Mapping[str, Any]:
                return {"is_on": _as_bool(device.value(sid, "on"))}

            async def turn_on(device: DeviceContext, _data: Mapping[str, Any]) -> None:
                await device.async_send_service(sid, {"on": 1})

            async def turn_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
                await device.async_send_service(sid, {"on": 0})

            return EntitySpec(
                platform="switch",
                key=sid,
                name=label,
                state=state,
                actions={"turn_on": turn_on, "turn_off": turn_off},
            )

        return tuple(
            _switch_spec(sid, label)
            for sid, label in _SWITCH_SERVICES
            if context.has_service(sid)
        )


ADAPTER = Product105HAdapter()
