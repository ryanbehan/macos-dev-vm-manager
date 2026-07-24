import Foundation

public struct RestoreImageRecord: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let source: String
    public let minimumCPUCount: Int
    public let minimumMemoryBytes: UInt64
    public let hardwareModelBase64: String

    public init(
        source: String,
        minimumCPUCount: Int,
        minimumMemoryBytes: UInt64,
        hardwareModelBase64: String
    ) {
        self.schemaVersion = 1
        self.source = source
        self.minimumCPUCount = minimumCPUCount
        self.minimumMemoryBytes = minimumMemoryBytes
        self.hardwareModelBase64 = hardwareModelBase64
    }
}

public struct InstallerProgressRecord: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let event: String
    public let fractionCompleted: Double?
    public let message: String?

    public init(event: String, fractionCompleted: Double? = nil, message: String? = nil) {
        self.schemaVersion = 1
        self.event = event
        self.fractionCompleted = fractionCompleted
        self.message = message
    }
}

public enum InstallerRecordEncoder {
    public static func encode<T: Encodable>(_ value: T) throws -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return String(decoding: try encoder.encode(value), as: UTF8.self)
    }
}
