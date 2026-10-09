"""User-contributed protocol for Huawei product X0A0 (华为 AI 音箱 FLMG-10).

设备类型: 华为 AI 音箱（FLMG-10；实测 2 台，左/右声道 stereo 配对）
制造商: 华为
Profile（profiles/X0A0.json）:
   smartspeaker.playControl enum RW  0=停止播放 1=启动播放 2=上一首 3=下一首
   audioplayer.playState  enum RW    0=暂停 1=播放中 2=停止
   speakerState.State     enum R     0=待机中 1=拾音中 2=等待响应 3=语音播报

本适配器暴露一个 media_player：播放 / 暂停 / 停止 / 上一首 / 下一首。
真机实测修正（官方 Profile 有两处笔误）:
- playControl 的 enumList 把「上一首」「下一首」都写成 2；实测 3 才是「下一首」。
- audioplayer.playState 虽标 RW，但写它一律被云端拒绝（errcode=-1）→ 暂停/停止只能走
  smartspeaker.playControl=0（资料写「停止播放」，实测效果=暂停，且能被 =1 恢复播放）；
  设备没有独立的「停止」态，故 pause 与 stop 同效。
- 音量字段在 X0A0 的 Profile 里未声明, 但官方 H5 插件(birdmusic)的
  setVolumeChange 直接写 {smartspeaker: {volume: 0-100}}(滑条百分比),
  且真机状态实报 volume/muteStatus 字段 → 本适配器支持音量与静音,
  推翻上文「不暴露音量」的原始结论(该结论仅对 Profile 声明范围成立)。

本地扩展（依据真机 service_states 实报字段, 官方 Profile 未声明）:
- media_player 增加 media_title：读 audioplayer.metadata（只读, 空串不显示）。
- media_player 增加音量：volume_level = smartspeaker.volume/100,
  set_volume 写 {smartspeaker: {volume: 0-100}}(官方插件同款命令, 已真机验证)。
- switch 蓝牙开关      smartspeaker.btSwitch   0/1
- switch DLNA 投播     smartspeaker.dlnaSwitch 0/1
- switch 音乐律动灯    musicLed.enable   0/1
- sensor  音箱状态     speakerState.State 只读枚举（真机字段名为 speakerState, 兼容 State）
  以上开关写命令沿用统一格式 {sid: {field: 0|1}}, 已真机验证。

不暴露的字段（真机实验结论）:
- 静音 smartspeaker.muteStatus: 只读有效, 写 0/1 无效果（真机实测）;
- 勿扰模式 quietMode.enable: App 内已有完整的定时配置界面, 集成内不投影;
- 环境灯 light 服务: 见下节。

环境灯（light 服务）不投影, 真机实验结论:
- App 的 6 种灯效配置不走云端通道, 云端 MQTT 状态里从未出现, 无法读取或复现;
- light 服务只是固定色覆盖: 关灯 {"on":0} 单字段生效(=回到机内默认灯效),
  开灯必须带 {"on":1,"brightness","colour","fadeTime"} 完整负载;
- colour 疑似 0xRRGGBB 整数: 0-10 全部渲染为暗蓝(仅蓝通道微亮), 
  brightness=100 被钳位回报为 1, 刻度不明;
- 无法达到 App 灯效效果, 故不暴露, 避免与 App 行为混淆。
"""
from __future__ import annotations

import json

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_STATE_PLAYING = "playing"
_STATE_PAUSED = "paused"
_STATE_IDLE = "idle"

_SPEAKER_STATE_TEXT = {0: "待机中", 1: "拾音中", 2: "等待响应", 3: "语音播报"}

_METADATA_TITLE_KEYS = ("title", "songName", "name", "mediaName", "songTitle")


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


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


def _metadata_title(value: Any) -> str | None:
    """从 audioplayer.metadata 提取可读标题（格式未知, 只做保守解析）。"""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return text
    if isinstance(parsed, dict):
        for key in _METADATA_TITLE_KEYS:
            item = parsed.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
        return None
    if isinstance(parsed, str) and parsed.strip():
        return parsed.strip()
    return None


async def _play(device: DeviceContext, _data: Mapping[str, Any]) -> None:
    await device.async_send_service("smartspeaker", {"playControl": 1})


async def _pause(device: DeviceContext, _data: Mapping[str, Any]) -> None:
    # 真机实测：写 audioplayer.playState 一律被云端拒（errcode=-1），
    # 暂停只能走 smartspeaker.playControl=0（资料叫「停止播放」，实际=暂停，可被 =1 恢复）
    await device.async_send_service("smartspeaker", {"playControl": 0})


async def _previous_track(device: DeviceContext, _data: Mapping[str, Any]) -> None:
    await device.async_send_service("smartspeaker", {"playControl": 2})


async def _next_track(device: DeviceContext, _data: Mapping[str, Any]) -> None:
    await device.async_send_service("smartspeaker", {"playControl": 3})


async def _set_volume(device: DeviceContext, data: Mapping[str, Any]) -> None:
    # 官方 H5 插件 setVolumeChange 的同款命令: volume 为 0-100 的百分比
    level = data.get("volume")
    if level is None:
        return
    percent = min(max(int(round(float(level) * 100)), 0), 100)
    await device.async_send_service("smartspeaker", {"volume": percent})


def _bool_switch_spec(
    sid: str, field: str, key: str, name: str
) -> EntitySpec | None:
    """按服务实际存在与否生成一个 0/1 开关实体。"""

    def state(device: DeviceContext) -> Mapping[str, Any]:
        return {"is_on": _as_bool(device.value(sid, field))}

    async def turn_on(device: DeviceContext, _data: Mapping[str, Any]) -> None:
        await device.async_send_service(sid, {field: 1})

    async def turn_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
        await device.async_send_service(sid, {field: 0})

    return EntitySpec(
        platform="switch",
        key=key,
        name=name,
        state=state,
        actions={"turn_on": turn_on, "turn_off": turn_off},
    )


class ProductX0A0Adapter:
    """X0A0 华为 AI 音箱：media_player + 开关 + 状态传感器。"""

    prod_id = "X0A0"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("audioplayer"):
            return ()
        specs: list[EntitySpec] = []

        def player_state(device: DeviceContext) -> Mapping[str, Any]:
            code = _as_int(device.value("audioplayer", "playState"))
            if code == 1:
                state = _STATE_PLAYING
            elif code == 0:
                state = _STATE_PAUSED
            else:
                state = _STATE_IDLE
            volume = _as_int(device.value("smartspeaker", "volume"))
            return {
                "state": state,
                "media_title": _metadata_title(
                    device.value("audioplayer", "metadata")
                ),
                "volume_level": volume / 100 if volume is not None and 0 <= volume <= 100 else None,
                "is_volume_muted": _as_bool(
                    device.value("smartspeaker", "muteStatus")
                ),
            }

        specs.append(
            EntitySpec(
                platform="media_player",
                key="speaker",
                name=None,
                state=player_state,
                actions={"play": _play, "pause": _pause, "stop": _pause,  # 设备无独立停止态
                         "previous": _previous_track, "next": _next_track,
                         "volume": _set_volume},
            )
        )

        for sid, field, key, name in (
            ("smartspeaker", "btSwitch", "bluetooth", "蓝牙开关"),
            ("smartspeaker", "dlnaSwitch", "dlna", "DLNA投播"),
            ("musicLed", "enable", "music_led", "音乐律动灯"),
        ):
            if context.has_service(sid):
                spec = _bool_switch_spec(sid, field, key, name)
                if spec is not None:
                    specs.append(spec)


        if context.has_service("speakerState"):
            def speaker_state(device: DeviceContext) -> Mapping[str, Any]:
                # Profile 声明字段名为 State, 真机状态实报字段名为 speakerState, 两者兼容
                code = _as_int(
                    device.value("speakerState", "State")
                    if device.value("speakerState", "State") is not None
                    else device.value("speakerState", "speakerState")
                )
                return {
                    "native_value": _SPEAKER_STATE_TEXT.get(code, str(code))
                    if code is not None
                    else None
                }

            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="speaker_state",
                    name="音箱状态",
                    state=speaker_state,
                )
            )
        return tuple(specs)


ADAPTER = ProductX0A0Adapter()
