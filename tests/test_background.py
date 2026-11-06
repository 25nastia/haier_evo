from copy import deepcopy
from datetime import timedelta
from unittest.mock import Mock

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.haier_evo.coordinator import HaierLaundryCoordinator
from test_laundry import create, control_fixture
from test_machine import setup_care_machine, phase_message


@pytest.mark.asyncio
@pytest.mark.parametrize('source', ['snapshot', 'push'])
@pytest.mark.parametrize('continuation', [False, True])
async def test_missed_finish_has_neutral_notice_only_after_stable_idle(hass, enable_custom_integrations, source, continuation):
    data = control_fixture()
    cloud, device, platform, events = await setup_care_machine(hass, data)
    device.on_message({'event': 'ProgramWasherBaseEvent', 'data': {
        'program': {'status': 'IN_PROGRESS', 'title': 'Mixed'}}})
    device.on_message(phase_message('2', 4))
    if source == 'snapshot':
        device.apply_snapshot(data, device._state_revision)
    else:
        device.on_message(phase_message('0', 0))
    await hass.async_block_till_done()
    assert device.program_status == 'idle' and not events
    if continuation:
        device.on_message({'event': 'ProgramWasherBaseEvent', 'data': {
            'program': {'status': 'IN_PROGRESS', 'title': 'Mixed'}}})
        device.on_message(phase_message('2', 3))
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await hass.async_block_till_done()
    if continuation:
        assert not events
    else:
        assert len(events) == 1
        assert events[0]['type'] == 'cycle_ended'
        assert events[0]['completion_reason'] == 'idle'
        assert events[0]['program'] == 'Mixed'
        assert not device.laundry_ready
        device.on_message(phase_message('0', 0))
        await hass.async_block_till_done()
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=30))
        await hass.async_block_till_done()
        assert len(events) == 1
    cloud.socket_app.send.assert_not_called()
    await platform.async_destroy()


@pytest.mark.asyncio
@pytest.mark.parametrize('cancelled', [False, True])
async def test_initial_idle_and_explicit_cancel_never_claim_finished(hass, enable_custom_integrations, cancelled):
    cloud, device, platform, events = await setup_care_machine(hass, control_fixture())
    if cancelled:
        device.on_message({'event': 'ProgramWasherBaseEvent', 'data': {
            'program': {'status': 'IN_PROGRESS', 'title': 'Mixed'}}})
        device.on_message({'event': 'ProgramWasherBaseEvent', 'data': {
            'program': {'status': 'CANCELLED', 'title': 'Mixed'}}})
    device.on_message(phase_message('0', 0))
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await hass.async_block_till_done()
    assert not events
    cloud.socket_app.send.assert_not_called()
    await platform.async_destroy()


@pytest.mark.asyncio
async def test_alarm_noise_cannot_keep_a_stale_running_cycle_fresh(hass):
    cloud, device = create('WM', control_fixture())
    cloud.hass = hass
    cloud.read_device_snapshot = Mock(return_value=control_fixture())
    device.on_message({'event': 'ProgramWasherBaseEvent', 'data': {
        'program': {'status': 'IN_PROGRESS', 'title': 'Mixed'}}})
    device._last_status_observed -= 46
    device.on_message({'event': 'alarms', 'payload': {'alarms': []}})
    coordinator = HaierLaundryCoordinator(hass, MockConfigEntry(domain='haier_evo'), device)
    await coordinator._async_update_data()
    cloud.read_device_snapshot.assert_called_once()
    cloud.socket_app.send.assert_not_called()
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_updates_run_without_a_frontend_or_open_popup(hass, enable_custom_integrations):
    cloud, device, platform, events = await setup_care_machine(hass, control_fixture())
    cloud.read_device_snapshot = Mock(return_value=control_fixture())
    assert device.recovery._unsub_refresh is not None
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=121))
    await hass.async_block_till_done()
    cloud.read_device_snapshot.assert_called_once()
    assert not events
    await platform.async_destroy()
