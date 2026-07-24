import AppKit
import Foundation
import VMRunnerCore

@main
enum VMRunnerMain {
    @MainActor
    static func main() {
        do {
            let configuration = try RunnerConfiguration.parse(
                arguments: Array(CommandLine.arguments.dropFirst())
            )
            let application = NSApplication.shared
            application.setActivationPolicy(.regular)
            let delegate = AppDelegate(configuration: configuration)
            application.delegate = delegate
            withExtendedLifetime(delegate) {
                application.run()
            }
        } catch {
            fputs("VMRunner: \(error)\n", stderr)
            exit(EXIT_FAILURE)
        }
    }
}
