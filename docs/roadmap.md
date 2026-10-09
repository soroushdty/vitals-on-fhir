# Roadmap

Phases are opened one at a time by a decision record. What has shipped is listed in the [README](../README.md#what-it-supports-today).

1. **Heart rate from wearables** (standard BLE Heart Rate Service). *Delivered.*
2. **Home health devices** via standard Bluetooth health profiles: `ScalarVital` and `ComponentVital` subclasses for blood pressure, pulse oximetry, temperature, and weight, a shared BLE connection with per-profile payload parsers, and device-reported timestamps. *Open ([ADR-0001](adr-0001-open-phase-2-home-health-devices.md)); all four vital signs have shipped.* Follow-ups are tracked as issues, for example reading the thermometer's static Temperature Type characteristic ([#26](https://github.com/soroushdty/vitals-on-fhir/issues/26)).
3. **Phone health aggregators** (Android Health Connect, Apple HealthKit) as new `DeviceAdapter` subclasses.

   *Preview note (context only; phase 3 is closed — do not build until opened via an ADR).* This is
   the correct integration path for consumer scales and wearables that use **proprietary** BLE rather
   than a standard Bluetooth health profile — e.g. the RENPHO Elis 1 body-composition scale
   (`amazon.com/dp/B01N1UX8RW`). Its BLE is proprietary, so a direct adapter would require reverse
   engineering, which `product.md` and `security-privacy.md` put permanently out of scope. But the
   RENPHO Health app can push to Apple Health, Fitbit, Google Fit, Samsung Health, and MyFitnessPal,
   and on Android **Health Connect** is the hub those apps read/write through. The flow becomes
   `device → vendor app → Health Connect / Apple Health → aggregator adapter → pipeline → FHIR`, reading
   only **documented, published APIs** — fully in-mission, unlike the BLE route. Design implications to
   weigh when this phase opens:
   - The adapter is **aggregator-specific, not vendor-specific**: one `HealthConnectAdapter` /
     `HealthKitAdapter` serves *any* upstream app feeding the store (RENPHO, Withings, manual entry).
     The RENPHO is motivation, not a target — there is no per-vendor "RENPHO connector."
   - **Body composition finds a clean home here.** Body fat %, basal metabolic rate, and lean body
     mass — which have no standard BLE channel and were correctly excluded from `weight-body-mass` —
     have typed Health Connect records (`BodyFatRecord`, `BasalMetabolicRateRecord`,
     `LeanBodyMassRecord`), so they can become new `ScalarVital` subclasses with their own FHIR
     Observations when wanted.
   - It **stresses the object model in a new way**: a query/poll-based *pull* from a local datastore
     rather than a live BLE notification stream, historical records carrying their own timestamps (real
     store-and-forward), and no single physical "device" behind `DeviceInfo`. The `DeviceAdapter` ABC
     (`vitals()` async generator) can express this, but `DeviceInfo` and the one-device-at-a-time
     assumption need revisiting. Expect a historical/batch pull, not near-real-time (NFR-1's real-time
     target was heart rate, not episodic weight).
   - **To evaluate when this phase opens: finished ECG recordings.** An aggregator may expose short
     ECG recordings that the device has already finished, such as Apple Watch 30-second strips in
     HealthKit, with the device's own classification. Relaying them, without processing, would follow
     the HL7 Personal Health Record IG's PGHD Electrocardiogram profile (`hl7.fhir.uv.phr`
     1.0.0-ballot2, build 2026-09-17: a parent Observation with `classification` and `symptomsStatus` components and
     one VoltageMeasurement Observation per lead in `hasMember`, each holding `valueSampledData`).
     Weigh it against the raw-signal exclusion in `product.md`: an ECG is not a vital sign, and the
     classification is a diagnosis-like statement. Whether Health Connect exposes ECG at all is
     checked in #61. Profile: <https://build.fhir.org/ig/HL7/personal-health-record-format-ig/en/StructureDefinition-pghd-voltage-measurement.html>.

   Sources reviewed for this note were rephrased for licensing compliance; see RENPHO's sync
   documentation and the Android Health Connect data-types reference.

4. **Persistence and outbound integration**: durable `ObservationStore` implementations, an `ObservationSink` that pushes to external FHIR servers, SMART on FHIR as an `Authenticator`, and adapter discovery through Python entry points.
5. **Additional concrete adapters**, contributed or third-party, including optional device-specific ones as separately licensed packages with clean-room implementations and documented provenance.
