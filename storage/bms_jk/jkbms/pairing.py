"""BlueZ pairing agent for the JK BMS BEKEN BLE module (PIN bonding).

Only usable on Linux with ``dbus-fast``; importing it is safe everywhere,
``dbus-fast`` is loaded lazily inside :meth:`BlueZPairingAgent.pair`.
"""

from __future__ import annotations

import logging
from typing import Optional

from .constants import DEFAULT_PIN

log = logging.getLogger("jkbms.pairing")


class BlueZPairingAgent:
    """Register a BlueZ agent answering the configured PIN, then bond.

    The DBus message bus is kept referenced on the instance so the exported
    agent is not garbage-collected mid-session.
    """

    def __init__(self, pin: str = DEFAULT_PIN) -> None:
        self.pin = pin
        self._bus = None

    async def pair(self, mac: str) -> bool:
        """Register the agent and pair/bond with ``mac``.

        Returns True when the agent was registered, False when ``dbus-fast``
        is unavailable (skipped) or the device is not yet known to BlueZ.
        """
        try:
            from dbus_fast import Message, Variant
            from dbus_fast.aio.message_bus import MessageBus
            from dbus_fast.constants import BusType
            from dbus_fast.service import ServiceInterface, method
        except ImportError:
            log.warning("dbus-fast not installed; skipping pairing step")
            return False

        class Agent(ServiceInterface):
            def __init__(self, pin: str) -> None:
                super().__init__("org.bluez.Agent1")
                self._pin = pin

            @method()
            def Release(self):
                pass

            @method()
            def RequestPinCode(self, d: "s") -> "s":
                log.info("PIN requested, sending %s", self._pin)
                return self._pin

            @method()
            def DisplayPinCode(self, d: "s", p: "s"):
                pass

            @method()
            def RequestPasskey(self, d: "s") -> "u":
                return int(self._pin)

            @method()
            def DisplayPasskey(self, d: "s", pk: "u", e: "y"):
                pass

            @method()
            def ConfirmModeAndPinCode(self, d: "s", kb: "b", pc: "s") -> "b":
                return True

            @method()
            def Authorize(self, d: "s", u: "s"):
                pass

            @method()
            def AuthorizeService(self, d: "s", u: "s"):
                pass

            @method()
            def Cancel(self):
                pass

        self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        agent = Agent(self.pin)
        self._bus.export("/jkbms/agent", agent)
        await self._bus.call(Message(
            destination="org.bluez", path="/org/bluez",
            interface="org.bluez.AgentManager1", member="RegisterAgent",
            signature="os", body=["/jkbms/agent", "KeyboardDisplay"]))
        await self._bus.call(Message(
            destination="org.bluez", path="/org/bluez",
            interface="org.bluez.AgentManager1", member="RequestDefaultAgent",
            signature="o", body=["/jkbms/agent"]))

        mgr = await self._bus.call(Message(
            destination="org.bluez", path="/",
            interface="org.freedesktop.DBus.ObjectManager",
            member="GetManagedObjects"))
        objs = mgr.body
        if isinstance(objs, (list, tuple)):
            for el in objs:
                if isinstance(el, dict):
                    objs = el
                    break
        dev_path = None
        for p, ifs in objs.items():
            if "org.bluez.Device1" in ifs:
                ad = ifs["org.bluez.Device1"].get("Address")
                if isinstance(ad, Variant):
                    ad = ad.value
                if ad and ad.upper() == mac.upper():
                    dev_path = p
        if not dev_path:
            log.warning("device %s not known to BlueZ yet (scan first)", mac)
            return False
        try:
            await self._bus.call(Message(
                destination="org.bluez", path=dev_path,
                interface="org.bluez.Device1", member="Pair"))
            log.info("paired/bonded with %s", mac)
        except Exception as e:
            if "AlreadyExists" in str(e):
                log.info("already bonded with %s", mac)
            else:
                log.warning("pair failed: %s", e)
        return True

    def close(self) -> None:
        """Disconnect the agent bus, unregistering the agent."""
        if self._bus is not None:
            try:
                self._bus.disconnect()
            except Exception as e:
                log.debug("agent bus disconnect failed: %s", e)
            self._bus = None
