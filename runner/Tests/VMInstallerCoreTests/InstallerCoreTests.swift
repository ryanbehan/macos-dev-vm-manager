import Testing
@testable import VMInstallerCore

@Test func encodesStableRestoreImageRecord() throws {
    let record = RestoreImageRecord(
        source: "https://updates.example.invalid/example.ipsw",
        minimumCPUCount: 4,
        minimumMemoryBytes: 4_294_967_296,
        hardwareModelBase64: "AA=="
    )
    let encoded = try InstallerRecordEncoder.encode(record)
    #expect(encoded.contains("\"schemaVersion\":1"))
    #expect(encoded.contains("\"minimumCPUCount\":4"))
}

@Test func encodesProgressRecord() throws {
    let record = InstallerProgressRecord(event: "progress", fractionCompleted: 0.5)
    let encoded = try InstallerRecordEncoder.encode(record)
    #expect(encoded.contains("\"fractionCompleted\":0.5"))
}

@Test func encodesCancellationRecord() throws {
    let record = InstallerProgressRecord(event: "cancelled")
    let encoded = try InstallerRecordEncoder.encode(record)
    #expect(encoded.contains("\"event\":\"cancelled\""))
}
