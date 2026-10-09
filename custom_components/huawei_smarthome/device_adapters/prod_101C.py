"""User-contributed protocol for Huawei product 101C (华为智选 欧普读写台灯 Reading lamp-CW).

设备类型: 书写台灯 (Reading lamp)
制造商: 欧普照明, 型号 Reading lamp-CW
核心服务 (单一 ``light`` 服务):
   light.on         bool RW 开关 (quickmenu: 1=开 0=关)
   light.brightness int  RW 亮度 0-255
   light.mode       int  RW 模式 (2=阅读模式 3=读写模式 4=夜灯模式)
   light.colorTemperature int RW 色温 2700-6500K (Profile 未声明,
        但设备实时状态上报该字段, 范围取自官方 H5 插件 cct 公式
        b=2700 + 3800 跨度)

本适配器暴露 1 个 HA ``light`` (亮度+色温) + 1 个灯光模式 ``select``。
timer/delay/name 特征不投影。

开关、亮度、色温写命令均已在真实设备上验证。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


def _field(profile: Mapping[str, Any], sid: str, name: str) -> Mapping[str, Any] | None:
    for service in profile.get("services", ()):
        if not isinstance(service, Mapping) or service.get("serviceId") != sid:
            continue
        for field in service.get("characteristics", ()):
            if isinstance(field, Mapping) and field.get("characteristicName") == name:
                return field
    return None


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.strip().casefold() in {"1", "true", "on"}:
            return True
        if value.strip().casefold() in {"0", "false", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _payload_int(value: Any) -> int:
    number = _number(value)
    return int(round(number)) if number is not None else value


def _enum_options(field: Mapping[str, Any]) -> tuple[tuple[str, Any], ...]:
    options: list[tuple[str, Any]] = []
    for item in field.get("enumList", ()):
        if not isinstance(item, Mapping) or item.get("enumVal") is None:
            continue
        label = str(item.get("descCh") or item.get("descEn") or item.get("enumVal")).strip()
        options.append((label, item["enumVal"]))
    return tuple(options)


def _enum_label(field: Mapping[str, Any], value: Any) -> str | None:
    number = _number(value)
    for label, raw in _enum_options(field):
        if number is not None and _number(raw) == number:
            return label
    return None


CCT_MIN_KELVIN = 2700
CCT_MAX_KELVIN = 6500


def _cct_kelvin(value: Any) -> int | None:
    number = _number(value)
    if number is None or number < CCT_MIN_KELVIN:
        return None
    return min(int(number), CCT_MAX_KELVIN)


async def _turn_on(context: DeviceContext, data: Mapping[str, Any]) -> None:
    await context.async_send_service("light", {"on": 1})
    brightness = data.get("brightness")
    if brightness is not None:
        value = min(max(int(brightness), 0), 255)
        await context.async_send_service("light", {"brightness": value})
    color_temp = data.get("color_temp_kelvin")
    if color_temp is not None:
        value = min(max(int(color_temp), CCT_MIN_KELVIN), CCT_MAX_KELVIN)
        await context.async_send_service("light", {"colorTemperature": value})


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("light", {"on": 0})


class Product101CAdapter:
    """101C 华为智选 欧普读写台灯适配器。"""

    prod_id = "101C"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None or not context.has_service("light"):
            return ()
        specs: list[EntitySpec] = []

        switch = _field(profile, "light", "on")
        brightness = _field(profile, "light", "brightness")
        if switch is not None:
            def light_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "is_on": _bool(device.value("light", "on")),
                    "brightness": (
                        min(max(int(number), 0), 255)
                        if (number := _number(device.value("light", "brightness")))
                        is not None
                        else None
                    ),
                    "color_temp_kelvin": _cct_kelvin(
                        device.value("light", "colorTemperature")
                    ),
                    "color_mode": "color_temp" if brightness is not None else "onoff",
                }

            metadata: dict[str, Any] = {
                "supported_color_modes": {"color_temp" if brightness is not None else "onoff"},
                "min_color_temp_kelvin": CCT_MIN_KELVIN,
                "max_color_temp_kelvin": CCT_MAX_KELVIN,
            }
            specs.append(
                EntitySpec(
                    platform="light",
                    key="light",
                    name=None,
                    state=light_state,
                    metadata=metadata,
                    actions={"turn_on": _turn_on, "turn_off": _turn_off},
                )
            )

        mode_field = _field(profile, "light", "mode")
        options = _enum_options(mode_field) if mode_field is not None else ()
        if mode_field is not None and options:

            async def select_mode(
                device: DeviceContext, data: Mapping[str, Any]
            ) -> None:
                option = str(data.get("option"))
                for label, raw in options:
                    if label == option:
                        await device.async_send_service(
                            "light", {"mode": _payload_int(raw)}
                        )
                        return
                raise ValueError(f"101C unknown light mode: {option}")

            specs.append(
                EntitySpec(
                    platform="select",
                    key="light_mode",
                    name="灯光模式",
                    state=lambda device: {
                        "current_option": _enum_label(
                            mode_field, device.value("light", "mode")
                        )
                    },
                    metadata={"options": tuple(label for label, _ in options)},
                    actions={"select_option": select_mode},
                )
            )
        return tuple(specs)


ADAPTER = Product101CAdapter()
