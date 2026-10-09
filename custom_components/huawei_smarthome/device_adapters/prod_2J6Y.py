"""Profile-based adapter for the DALEN Smart Table Lamp 3i (2J6Y).

The public Profile declares a primary ``switch``/``brightness`` lamp and the
``lightMode`` presets.  This adapter projects those basic lighting controls
only.  Night wake-up, toggle, timers, records, fade time, indicators,
backlight, network data and firmware management are not part of the basic
lamp projection.

The mapping is based on the public Profile.  It has not been verified on a
physical device.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


_SWITCH_SID = "switch"
_SWITCH_FIELD = "on"
_BRIGHTNESS_SID = "brightness"
_BRIGHTNESS_FIELD = "brightness"
_LIGHT_MODE_SID = "lightMode"
_LIGHT_MODE_FIELD = "mode"


def _field(
    profile: Mapping[str, Any],
    sid: str,
    name: str,
) -> Mapping[str, Any] | None:
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
        text = value.strip().casefold()
        if text in {"1", "true", "on"}:
            return True
        if text in {"0", "false", "off"}:
            return False
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _range(field: Mapping[str, Any] | None) -> tuple[float, float] | None:
    if field is None:
        return None
    minimum = _number(field.get("min"))
    maximum = _number(field.get("max"))
    if minimum is None or maximum is None or maximum <= minimum:
        return None
    return float(minimum), float(maximum)


def _payload_number(value: Any, field: Mapping[str, Any]) -> int | float:
    number = _number(value)
    if number is None:
        raise ValueError("2J6Y value must be numeric")
    if str(field.get("characteristicType") or "").casefold() in {
        "int",
        "integer",
        "enum",
    }:
        return int(round(number))
    return int(number) if float(number).is_integer() else number


def _device_brightness_to_ha(
    value: Any,
    field: Mapping[str, Any],
) -> int | None:
    number = _number(value)
    value_range = _range(field)
    if number is None or value_range is None:
        return None
    minimum, maximum = value_range
    number = min(max(float(number), minimum), maximum)
    return round((number - minimum) * 255 / (maximum - minimum))


def _ha_brightness_to_device(
    value: Any,
    field: Mapping[str, Any],
) -> int | float:
    number = _number(value)
    value_range = _range(field)
    if number is None or value_range is None:
        raise ValueError("2J6Y brightness range is missing from the Profile")
    minimum, maximum = value_range
    number = min(max(float(number), 0), 255)
    return _payload_number(
        minimum + number * (maximum - minimum) / 255,
        field,
    )


def _enum_options(field: Mapping[str, Any]) -> tuple[tuple[str, Any], ...]:
    options: list[tuple[str, Any]] = []
    for item in field.get("enumList", ()):
        if not isinstance(item, Mapping) or item.get("enumVal") is None:
            continue
        label = item.get("descCh") or item.get("descEn") or item["enumVal"]
        options.append((str(label), item["enumVal"]))
    return tuple(options)


def _enum_label(field: Mapping[str, Any], value: Any) -> str | None:
    number = _number(value)
    for label, raw in _enum_options(field):
        if number is not None and _number(raw) == number:
            return label
        if str(raw) == str(value):
            return label
    return None


async def _turn_on(context: DeviceContext, data: Mapping[str, Any]) -> None:
    """Turn on first, then apply a requested brightness value."""

    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 1})
    brightness = data.get("brightness")
    if brightness is None:
        return
    field = _field(
        context.profile or {},
        _BRIGHTNESS_SID,
        _BRIGHTNESS_FIELD,
    )
    if field is None:
        raise ValueError("2J6Y brightness field is missing from the Profile")
    await context.async_send_service(
        _BRIGHTNESS_SID,
        {_BRIGHTNESS_FIELD: _ha_brightness_to_device(brightness, field)},
    )


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 0})


class Product2J6YAdapter:
    """DALEN Smart Table Lamp 3i basic projection."""

    prod_id = "2J6Y"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        switch = _field(profile, _SWITCH_SID, _SWITCH_FIELD)
        brightness = _field(profile, _BRIGHTNESS_SID, _BRIGHTNESS_FIELD)
        brightness_range = _range(brightness)
        specs: list[EntitySpec] = []

        if switch is not None and brightness_range is not None:

            def light_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "is_on": _bool(device.value(_SWITCH_SID, _SWITCH_FIELD)),
                    "brightness": _device_brightness_to_ha(
                        device.value(_BRIGHTNESS_SID, _BRIGHTNESS_FIELD),
                        brightness,
                    ),
                    "color_mode": "brightness",
                }

            specs.append(
                EntitySpec(
                    platform="light",
                    key="light",
                    name=None,
                    state=light_state,
                    metadata={"supported_color_modes": {"brightness"}},
                    actions={"turn_on": _turn_on, "turn_off": _turn_off},
                )
            )

        light_mode = _field(profile, _LIGHT_MODE_SID, _LIGHT_MODE_FIELD)
        options = _enum_options(light_mode) if light_mode is not None else ()
        if light_mode is not None and options:

            async def select_light_mode(
                device: DeviceContext,
                data: Mapping[str, Any],
            ) -> None:
                option = str(data.get("option"))
                for label, raw in options:
                    if label == option:
                        await device.async_send_service(
                            _LIGHT_MODE_SID,
                            {_LIGHT_MODE_FIELD: _payload_number(raw, light_mode)},
                        )
                        return
                raise ValueError(f"2J6Y unknown light mode: {option}")

            specs.append(
                EntitySpec(
                    platform="select",
                    key="light_mode",
                    name="灯光模式",
                    state=lambda device: {
                        "current_option": _enum_label(
                            light_mode,
                            device.value(_LIGHT_MODE_SID, _LIGHT_MODE_FIELD),
                        )
                    },
                    metadata={"options": tuple(label for label, _ in options)},
                    actions={"select_option": select_light_mode},
                )
            )

        return tuple(specs)


ADAPTER = Product2J6YAdapter()
