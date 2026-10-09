"""Profile-based adapter for the OPPLE MX650 ceiling light (1080).

The public Profile declares a primary ``switch``/``brightness`` light, a
colour-temperature service, and a ``colourMode`` selector.  It does not expose
RGB or HSB component fields, so this adapter deliberately projects the device
as a brightness and colour-temperature light only.  Timers, delay, OTA,
network data and preset light modes are not part of this basic projection.

The mapping is derived from the public Profile and Huawei's service model.  It
has not been verified on a physical device.
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
_COLOUR_MODE_SID = "colourMode"
_COLOUR_MODE_FIELD = "colourMode"
_COLOUR_MODE_COLOR_TEMP = 1
_CCT_SID = "cct"
_CCT_FIELD = "colorTemperature"


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
        raise ValueError("1080 value must be numeric")
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
        raise ValueError("1080 brightness range is missing from the Profile")
    minimum, maximum = value_range
    number = min(max(float(number), 0), 255)
    return _payload_number(
        minimum + number * (maximum - minimum) / 255,
        field,
    )


async def _turn_on(context: DeviceContext, data: Mapping[str, Any]) -> None:
    """Turn on first, then apply requested brightness or colour temperature."""

    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 1})
    profile = context.profile or {}

    brightness = data.get("brightness")
    brightness_field = _field(profile, _BRIGHTNESS_SID, _BRIGHTNESS_FIELD)
    if brightness is not None:
        if brightness_field is None:
            raise ValueError("1080 brightness field is missing from the Profile")
        await context.async_send_service(
            _BRIGHTNESS_SID,
            {
                _BRIGHTNESS_FIELD: _ha_brightness_to_device(
                    brightness,
                    brightness_field,
                )
            },
        )

    color_temp_kelvin = data.get("color_temp_kelvin")
    cct_field = _field(profile, _CCT_SID, _CCT_FIELD)
    cct_range = _range(cct_field)
    if color_temp_kelvin is not None:
        if cct_field is None or cct_range is None:
            raise ValueError("1080 color-temperature range is missing from the Profile")
        await context.async_send_service(
            _COLOUR_MODE_SID,
            {_COLOUR_MODE_FIELD: _COLOUR_MODE_COLOR_TEMP},
        )
        minimum, maximum = cct_range
        value = min(max(float(color_temp_kelvin), minimum), maximum)
        await context.async_send_service(
            _CCT_SID,
            {_CCT_FIELD: _payload_number(value, cct_field)},
        )


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 0})


class Product1080Adapter:
    """OPPLE MX650 ceiling light basic projection."""

    prod_id = "1080"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        switch = _field(profile, _SWITCH_SID, _SWITCH_FIELD)
        brightness = _field(profile, _BRIGHTNESS_SID, _BRIGHTNESS_FIELD)
        brightness_range = _range(brightness)
        colour_mode = _field(profile, _COLOUR_MODE_SID, _COLOUR_MODE_FIELD)
        cct = _field(profile, _CCT_SID, _CCT_FIELD)
        cct_range = _range(cct) if colour_mode is not None else None
        if switch is None or brightness_range is None:
            return ()

        color_mode = "color_temp" if cct_range is not None else "brightness"

        def light_state(device: DeviceContext) -> Mapping[str, Any]:
            return {
                "is_on": _bool(device.value(_SWITCH_SID, _SWITCH_FIELD)),
                "brightness": _device_brightness_to_ha(
                    device.value(_BRIGHTNESS_SID, _BRIGHTNESS_FIELD),
                    brightness,
                ),
                "color_temp_kelvin": (
                    _number(device.value(_CCT_SID, _CCT_FIELD))
                    if cct_range is not None
                    else None
                ),
                "color_mode": color_mode,
            }

        metadata: dict[str, Any] = {
            "supported_color_modes": {color_mode},
        }
        if cct_range is not None:
            metadata["min_color_temp_kelvin"] = int(cct_range[0])
            metadata["max_color_temp_kelvin"] = int(cct_range[1])
        return (
            EntitySpec(
                platform="light",
                key="light",
                name=None,
                state=light_state,
                metadata=metadata,
                actions={"turn_on": _turn_on, "turn_off": _turn_off},
            ),
        )


ADAPTER = Product1080Adapter()
