# Device compatibility

| Device | Status |
|---|---|
| Xiaomi Smart Band 10 (HR broadcast enabled) | Shipped: `MiBand10Adapter` |
| Other devices with HR broadcast (e.g., some Amazfit, Garmin, Polar, Coros models) | Supported by subclassing `BleHeartRateAdapter`; unverified |
| BLE chest straps (standard Heart Rate Service) | Supported by subclassing `BleHeartRateAdapter`; unverified |
| BLE blood-pressure cuffs (standard Blood Pressure Service `0x1810`) | Supported via `BloodPressureBleAdapter` (composes the shared `BleConnection` lifecycle); unverified against specific devices |
| BLE pulse oximeters (standard Pulse Oximeter Service `0x1822`) | Supported via `PulseOximeterBleAdapter` (composes the shared `BleConnection` lifecycle); unverified against specific devices |
| BLE thermometers (standard Health Thermometer Service `0x1809`) | Supported via `HealthThermometerBleAdapter` (composes the shared `BleConnection` lifecycle); unverified against specific devices |
| Apple Watch, Oura, most Wear OS watches | Not supported: no native open real-time channel |

Please report devices you've tested, or contribute your adapter, via an issue.

**Known limitations of the standard channel:** it streams live data only (no stored history), provides device-computed beats per minute rather than raw PPG, may require an active workout mode on some devices, and is unauthenticated at the Bluetooth level (see [Security](../README.md#security--privacy)).
