# Roadmap

1. **Heart rate from wearables** (standard BLE Heart Rate Service). *MVP*
2. **Home health devices** via standard Bluetooth health profiles: new `ScalarVital` and `ComponentVital` subclasses for blood pressure, pulse oximetry, temperature, and weight, plus a generalized BLE adapter with per-profile payload parsers and support for store-and-forward readings.
3. **Phone health aggregators** (Android Health Connect, Apple HealthKit) as new `DeviceAdapter` subclasses.
4. **Persistence and outbound integration**: durable `ObservationStore` implementations, an `ObservationSink` that pushes to external FHIR servers, SMART on FHIR as an `Authenticator`, and adapter discovery through Python entry points.
5. **Additional concrete adapters**, contributed or third-party, including optional device-specific ones as separately licensed packages with clean-room implementations and documented provenance.
