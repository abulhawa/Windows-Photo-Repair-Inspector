using System.Globalization;
using System.Text.RegularExpressions;

namespace PhotoRepair.Core;

public static class Timestamps
{
    public const string DisplayFormat = "yyyy-MM-dd HH:mm:ss";
    public static string Format(DateTimeOffset value) => value.ToLocalTime().ToString(DisplayFormat, CultureInfo.InvariantCulture);
    public static DateTimeOffset? Parse(string? value) =>
        DateTime.TryParseExact(value, DisplayFormat, CultureInfo.InvariantCulture, DateTimeStyles.None, out var wall)
            ? new DateTimeOffset(DateTime.SpecifyKind(wall, DateTimeKind.Unspecified), TimeZoneInfo.Local.GetUtcOffset(wall)) : null;

    public static (string Token, DateTimeOffset Timestamp)? ExtractEpoch(string filename)
    {
        foreach (Match match in Regex.Matches(Path.GetFileNameWithoutExtension(filename), @"(?<!\d)\d{10}(?:\d{3})?(?!\d)"))
        {
            long value = long.Parse(match.Value, CultureInfo.InvariantCulture);
            var time = DateTimeOffset.FromUnixTimeMilliseconds(match.Length == 10 ? value * 1000 : value).ToLocalTime();
            if (time.Year is >= 2004 and <= 2100) return (match.Value, time);
        }
        return null;
    }

    public static DateTimeOffset? FromFilename(string filename)
    {
        string stem = Path.GetFileNameWithoutExtension(filename);
        string[] fullPatterns = [
            @"(?<!\d)(20\d{2})[-_.]?([01]\d)[-_.]?([0-3]\d)[ _T.-]+([0-2]\d)[.:_-]?([0-5]\d)[.:_-]?([0-5]\d)(?:\d{3})?(?!\d)",
            @"(?<!\d)(20\d{2})[-_.]([01]\d)[-_.]([0-3]\d).*?([0-2]\d)[.:_-]([0-5]\d)[.:_-]([0-5]\d)(?:\d{3})?(?!\d)"
        ];
        foreach (string pattern in fullPatterns)
        {
            var m = Regex.Match(stem, pattern);
            if (!m.Success) continue;
            var date = Parse($"{m.Groups[1]}-{m.Groups[2]}-{m.Groups[3]} {m.Groups[4]}:{m.Groups[5]}:{m.Groups[6]}");
            if (date is not null) return date;
        }
        string[] datePatterns = [
            @"(?<!\d)(20\d{2})([-_.]?)(0[1-9]|1[0-2])\2(0[1-9]|[12]\d|3[01])(?!\d)",
            @"(?<!\d)(0[1-9]|1[0-2])([-_.])(0[1-9]|[12]\d|3[01])\2(20\d{2})(?!\d)"
        ];
        for (int i = 0; i < datePatterns.Length; i++)
        {
            var m = Regex.Match(stem, datePatterns[i]);
            if (!m.Success) continue;
            var date = i == 0 ? Parse($"{m.Groups[1]}-{m.Groups[3]}-{m.Groups[4]} 00:00:00")
                : Parse($"{m.Groups[4]}-{m.Groups[1]}-{m.Groups[3]} 00:00:00");
            if (date is not null) return date;
        }
        return ExtractEpoch(filename)?.Timestamp;
    }
}
