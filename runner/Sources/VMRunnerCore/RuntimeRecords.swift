import Darwin
import Foundation

public struct RuntimeRecord: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let pid: Int32?
    public let state: String
    public let vmBundle: String
    public let updatedAt: String
    public let message: String?

    public init(
        pid: Int32?,
        state: String,
        vmBundle: String,
        message: String? = nil,
        updatedAt: String = ISO8601DateFormatter().string(from: Date())
    ) {
        self.schemaVersion = 1
        self.pid = pid
        self.state = state
        self.vmBundle = vmBundle
        self.updatedAt = updatedAt
        self.message = message
    }
}

public struct ControlResponse: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let status: String
    public let message: String
    public let updatedAt: String

    public init(
        status: String,
        message: String,
        updatedAt: String = ISO8601DateFormatter().string(from: Date())
    ) {
        self.schemaVersion = 1
        self.status = status
        self.message = message
        self.updatedAt = updatedAt
    }
}

public enum ControlSignal: Int32, Equatable, Sendable {
    case shutdown = 30 // SIGUSR1 on Darwin
    case suspend = 31  // SIGUSR2 on Darwin
}

public final class AtomicRecordWriter: @unchecked Sendable {
    public init() {}

    public func write<T: Encodable>(_ value: T, to url: URL) throws {
        try FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(),
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o700],
            ofItemAtPath: url.deletingLastPathComponent().path
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(value)
        try data.write(to: url, options: .atomic)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o600],
            ofItemAtPath: url.path
        )
    }
}
