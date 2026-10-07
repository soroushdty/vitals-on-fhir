# Device compatibility

| Device | Status |
|---|---|
| Xiaomi Smart Band 10 (HR broadcast enabled) | Shipped: `MiBand10Adapter` |
| Other devices with HR broadcast (e.g., some Amazfit, Garmin, Polar, Coros models) | Supported by subclassing `BleHeartRateAdapter`; unverified |
| BLE chest straps (standard Heart Rate Service) | Supported by subclassing `BleHeartRateAdapter`; unverified |
| BLE blood-pressure cuffs (standard Blood Pressure Service `0x1810`) | Supported via `BloodPressureBleAdapter` (composes the shared `BleConnection` lifecycle); unverified against specific devices |
| BLE pulse oximeters (standard Pulse Oximeter Service `0x1822`) | Supported via `PulseOximeterBleAdapter` (composes the shared `BleConnection` lifecycle); unverified against specific devices |
| BLE thermometers (standard Health Thermometer Service `0x1809`) | Supported via `HealthThermometerBleAdapter` (composes the shared `BleConnection` lifecycle); unverified against specific devices |
| BLE weight scales (standard Weight Scale Service `0x181D`) | Supported via `WeightScaleBleAdapter` (composes the shared `BleConnection` lifecycle); unverified against specific devices |
| Consumer body-composition scales using proprietary BLE (e.g. RENPHO Elis 1 and similar bioimpedance scales) | Not supported here: they do not expose the standard Weight Scale Service. Their route is the phase-3 phone-aggregator path (vendor app → Health Connect / Apple Health → aggregator adapter); see `docs/roadmap.md` |
| Apple Watch, Oura, most Wear OS watches | Not supported: no native open real-time channel |

Please report devices you've tested, or contribute your adapter, via an issue.

**Known limitations of the standard channel:** it streams live data only (no stored history), provides device-computed beats per minute rather than raw PPG, may require an active workout mode on some devices, and is unauthenticated at the Bluetooth level (see [Security](../README.md#security--privacy)).

## Troubleshooting: the device is not found

While no device is connected, the service keeps looking and says why each attempt failed, in the terminal and under **Connection status** on the dashboard. The messages and what to do:

| Message | What to check |
|---|---|
| `found '<name>' … but none matched (VOF_DEVICE_NAME is '<value>' …)` | `VOF_DEVICE_NAME` must be part of the device's advertised name (any case), such as `Smart Band 10`. The message lists the names that were seen. Leave it empty to take the first matching device. |
| `no device with service 0x180D found; check that it is on, in range and broadcasting …` | Nothing nearby is advertising the service. See below. |

When nothing is advertising:

1. **Switch the device's broadcast off and on again.** A Xiaomi Smart Band 10 was seen to stop advertising while its heart-rate broadcast setting still showed as on, with a charged battery; turning the setting off and on brought it back within seconds (observed 2026-10-07).
2. **Charge it.** A band at a few percent battery may stop broadcasting.
3. **Free it from the phone.** If the vendor app keeps the device connected, switch the phone's Bluetooth off for a minute.
4. **Check what the computer sees.** On Linux, `bluetoothctl --timeout 15 scan on` lists advertising devices, and `bluetoothctl info <address>` shows whether a known device is paired or connected. A device that is already connected to this computer does not advertise; the service finds and uses it anyway (Linux only).

The service does not need a restart: it connects within about 30 seconds of the device reappearing.
