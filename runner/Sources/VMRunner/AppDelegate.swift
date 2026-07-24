// Portions adapted from Apple sample code. See THIRD_PARTY_NOTICES.md.

import AppKit
import Darwin
import Foundation
import Virtualization
import VMRunnerCore

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private enum TerminationMode {
        case suspend
        case shutdown
    }

    private let configuration: RunnerConfiguration
    private let paths: VMPaths
    private let recordWriter = AtomicRecordWriter()
    private var window: NSWindow?
    private var virtualMachineView: VZVirtualMachineView?
    private var virtualMachine: VZVirtualMachine?
    private var virtualMachineDelegate: VMDelegate?
    private var shutdownSignalSource: DispatchSourceSignal?
    private var suspendSignalSource: DispatchSourceSignal?
    private var terminationMode: TerminationMode = .suspend
    private var suspendInProgress = false

    init(configuration: RunnerConfiguration) {
        self.configuration = configuration
        self.paths = VMPaths(
            bundle: configuration.vmBundle,
            controlDirectory: configuration.controlDirectory
        )
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        do {
            try FileManager.default.createDirectory(
                at: paths.controlDirectory,
                withIntermediateDirectories: true
            )
            installSignalSources()
            createWindow()
            try createVirtualMachine()
            startOrRestoreVirtualMachine()
        } catch {
            writeRuntime(state: "error", message: String(describing: error))
            terminateAfterFailure()
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard terminationMode == .suspend else {
            return .terminateNow
        }
        beginSuspend()
        return .terminateCancel
    }

    private func beginSuspend() {
        guard !suspendInProgress, let virtualMachine else { return }
        suspendInProgress = true
        switch virtualMachine.state {
        case .running:
            writeRuntime(state: "suspending")
            virtualMachine.pause { [weak self] result in
                guard let self else { return }
                switch result {
                case .failure(let error):
                    self.writeRuntime(state: "error", message: "Pause failed: \(error)")
                    self.suspendInProgress = false
                case .success:
                    self.saveAndTerminate()
                }
            }
        case .paused:
            saveAndTerminate()
        default:
            writeRuntime(
                state: "error",
                message: "Cannot suspend a VM in state \(virtualMachine.state.rawValue)."
            )
            suspendInProgress = false
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        shutdownSignalSource?.cancel()
        suspendSignalSource?.cancel()
    }

    private func createWindow() {
        let frame = NSRect(x: 0, y: 0, width: 1200, height: 750)
        let window = NSWindow(
            contentRect: frame,
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "macOS VM"
        window.center()
        let view = VZVirtualMachineView(frame: frame)
        view.autoresizingMask = [.width, .height]
        view.capturesSystemKeys = true
        view.automaticallyReconfiguresDisplay = true
        window.contentView = view
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        self.window = window
        self.virtualMachineView = view
    }

    private func createVirtualMachine() throws {
        let vmConfiguration = try VMConfigurationBuilder(paths: paths).build()
        let virtualMachine = VZVirtualMachine(configuration: vmConfiguration)
        let delegate = VMDelegate()
        delegate.didStop = { [weak self] in
            Task { @MainActor in self?.guestDidStop() }
        }
        delegate.didStopWithError = { [weak self] error in
            Task { @MainActor in self?.guestDidStop(error: error) }
        }
        virtualMachine.delegate = delegate
        virtualMachineView?.virtualMachine = virtualMachine
        self.virtualMachine = virtualMachine
        self.virtualMachineDelegate = delegate
    }

    private func startOrRestoreVirtualMachine() {
        guard let virtualMachine else { return }
        writeRuntime(state: "starting")
        if FileManager.default.fileExists(atPath: paths.saveFile.path) {
            writeRuntime(state: "restoring")
            virtualMachine.restoreMachineStateFrom(url: paths.saveFile) { [weak self] error in
                guard let self else { return }
                if let error {
                    self.writeRuntime(
                        state: "error",
                        message: "Saved-state restore failed; the save file was preserved: \(error)"
                    )
                    self.terminateAfterFailure()
                } else {
                    virtualMachine.resume { [weak self] result in
                        self?.handleStartResult(result, removeSavedState: true)
                    }
                }
            }
        } else {
            startVirtualMachine()
        }
    }

    private func startVirtualMachine() {
        virtualMachine?.start { [weak self] result in
            self?.handleStartResult(result)
        }
    }

    private func handleStartResult(
        _ result: Result<Void, Error>,
        removeSavedState: Bool = false
    ) {
        switch result {
        case .success:
            if removeSavedState {
                try? FileManager.default.removeItem(at: paths.saveFile)
            }
            writeRuntime(state: "running")
        case .failure(let error):
            writeRuntime(state: "error", message: "VM start failed: \(error)")
            terminateAfterFailure()
        }
    }

    private func terminateAfterFailure() {
        terminationMode = .shutdown
        NSApp.terminate(nil)
    }

    private func saveAndTerminate() {
        guard let virtualMachine else {
            suspendInProgress = false
            return
        }
        virtualMachine.saveMachineStateTo(url: paths.saveFile) { [weak self] error in
            guard let self else { return }
            if let error {
                self.writeRuntime(state: "error", message: "Save failed: \(error)")
                self.suspendInProgress = false
            } else {
                self.writeRuntime(state: "suspended", pid: nil)
                self.terminationMode = .shutdown
                NSApp.terminate(nil)
            }
        }
    }

    private func installSignalSources() {
        signal(SIGUSR1, SIG_IGN)
        signal(SIGUSR2, SIG_IGN)

        let shutdownSource = DispatchSource.makeSignalSource(signal: SIGUSR1, queue: .main)
        shutdownSource.setEventHandler { [weak self] in self?.requestGuestShutdown() }
        shutdownSource.resume()
        shutdownSignalSource = shutdownSource

        let suspendSource = DispatchSource.makeSignalSource(signal: SIGUSR2, queue: .main)
        suspendSource.setEventHandler { [weak self] in
            self?.terminationMode = .suspend
            self?.beginSuspend()
        }
        suspendSource.resume()
        suspendSignalSource = suspendSource
    }

    private func requestGuestShutdown() {
        guard let virtualMachine else {
            writeControlResponse(status: "rejected", message: "Virtual machine is unavailable.")
            return
        }
        guard virtualMachine.canRequestStop else {
            writeControlResponse(
                status: "rejected",
                message: "Guest macOS cannot accept a shutdown request in its current state."
            )
            return
        }
        do {
            terminationMode = .shutdown
            try virtualMachine.requestStop()
            writeRuntime(state: "shutdown-requested")
            writeControlResponse(status: "accepted", message: "Guest shutdown requested.")
        } catch {
            terminationMode = .suspend
            writeControlResponse(status: "rejected", message: String(describing: error))
        }
    }

    private func guestDidStop(error: Error? = nil) {
        terminationMode = .shutdown
        try? FileManager.default.removeItem(at: paths.saveFile)
        if let error {
            writeRuntime(state: "error", pid: nil, message: String(describing: error))
        } else {
            writeRuntime(state: "shutdown", pid: nil)
        }
        NSApp.terminate(nil)
    }

    private func writeRuntime(state: String, pid: Int32? = getpid(), message: String? = nil) {
        let record = RuntimeRecord(
            pid: pid,
            state: state,
            vmBundle: paths.bundle.path,
            message: message
        )
        do {
            try recordWriter.write(record, to: paths.runtimeFile)
        } catch {
            NSLog("Failed to write runtime status: %@", String(describing: error))
        }
    }

    private func writeControlResponse(status: String, message: String) {
        do {
            try recordWriter.write(
                ControlResponse(status: status, message: message),
                to: paths.controlResponseFile
            )
        } catch {
            NSLog("Failed to write control response: %@", String(describing: error))
        }
    }
}
