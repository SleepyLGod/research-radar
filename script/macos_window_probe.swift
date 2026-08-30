import CoreGraphics
import Foundation

guard CommandLine.arguments.count == 3,
      let pid = Int32(CommandLine.arguments[1]),
      let timeout = Double(CommandLine.arguments[2])
else {
    FileHandle.standardError.write(Data("usage: macos-window-probe <pid> <timeout>\n".utf8))
    exit(2)
}

let started = ContinuousClock.now
while ContinuousClock.now - started < .seconds(timeout) {
    let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
    let windows = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]] ?? []
    for window in windows {
        guard let owner = window[kCGWindowOwnerPID as String] as? NSNumber,
              owner.int32Value == pid,
              let layer = window[kCGWindowLayer as String] as? NSNumber,
              layer.intValue == 0,
              let number = window[kCGWindowNumber as String] as? NSNumber
        else { continue }
        let duration = ContinuousClock.now - started
        let components = duration.components
        let seconds = Double(components.seconds)
            + Double(components.attoseconds) / 1_000_000_000_000_000_000
        let result: [String: Any] = [
            "window_id": number.intValue,
            "probe_seconds": seconds,
        ]
        let data = try JSONSerialization.data(withJSONObject: result)
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data("\n".utf8))
        exit(0)
    }
    Thread.sleep(forTimeInterval: 0.01)
}

FileHandle.standardError.write(Data("No visible ResearchRadar window was observed.\n".utf8))
exit(1)
