import Foundation
import Testing
@testable import ResearchRadarCore

@Suite struct ReportDateTests {
    @Test func wireDateRetainsTheLocalDayAcrossUtcAndYearBoundaries() throws {
        for (instant, zone, expected) in [
            ("2026-12-31T23:30:00Z", "Asia/Hong_Kong", "2027-01-01"),
            ("2026-12-31T23:30:00Z", "America/Los_Angeles", "2026-12-31"),
            ("2026-12-31T23:30:00Z", "UTC", "2026-12-31"),
            ("2027-01-01T00:30:00Z", "Asia/Hong_Kong", "2027-01-01"),
            ("2027-01-01T00:30:00Z", "America/Los_Angeles", "2026-12-31"),
            ("2027-01-01T00:30:00Z", "UTC", "2027-01-01"),
            ("2028-03-01T00:30:00Z", "America/Los_Angeles", "2028-02-29"),
        ] {
            let date = try #require(ISO8601DateFormatter().date(from: instant))
            let timeZone = try #require(TimeZone(identifier: zone))
            #expect(ReportDate.string(for: date, timeZone: timeZone) == expected)
        }
    }
}
