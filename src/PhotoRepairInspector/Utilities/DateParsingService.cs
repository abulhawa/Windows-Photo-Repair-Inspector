using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;

namespace PhotoRepairInspector.Utilities;

public static class DateParsingService
{
    private static readonly IReadOnlyList<Func<string, DateTime?>> Parsers = new List<Func<string, DateTime?>>
    {
        ParseExact("IMG_(?<date>\\d{8})_(?<time>\\d{6})"),
        ParseExact("PXL_(?<date>\\d{8})_(?<time>\\d{6})"),
        ParseExact("VID_(?<date>\\d{8})_(?<time>\\d{6})"),
        ParseExact("(?<!\\d)(?<date>\\d{8})_(?<time>\\d{6})(?!\\d)"),
        ParseExact("(?<!\\d)(?<date>\\d{8})(?!\\d)", hasTime: false),
        ParseWhatsApp(),
        ParseWindowsExport(),
        ParseGenericDatePrefix()
    };

    public static DateTime? TryParse(string fileName)
    {
        foreach (var parser in Parsers)
        {
            var value = parser(fileName);
            if (value.HasValue)
            {
                return value;
            }
        }
        return null;
    }

    private static Func<string, DateTime?> ParseExact(string pattern, bool hasTime = true)
    {
        var regex = new Regex(pattern, RegexOptions.IgnoreCase | RegexOptions.Compiled);
        return fileName =>
        {
            var match = regex.Match(fileName);
            if (!match.Success)
            {
                return null;
            }

            var datePart = match.Groups["date"].Value;
            if (!DateTime.TryParseExact(datePart, "yyyyMMdd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var date))
            {
                return null;
            }

            if (!hasTime)
            {
                return date;
            }

            var timePart = match.Groups["time"].Value;
            if (!DateTime.TryParseExact(timePart, "HHmmss", CultureInfo.InvariantCulture, DateTimeStyles.None, out var time))
            {
                return date;
            }

            return date.Date + time.TimeOfDay;
        };
    }

    private static Func<string, DateTime?> ParseWhatsApp()
    {
        var regex = new Regex("IMG-(?<date>\\d{8})-WA\\d+", RegexOptions.IgnoreCase | RegexOptions.Compiled);
        return fileName =>
        {
            var match = regex.Match(fileName);
            if (!match.Success)
            {
                return null;
            }

            var datePart = match.Groups["date"].Value;
            return DateTime.TryParseExact(datePart, "yyyyMMdd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var date)
                ? date
                : null;
        };
    }

    private static Func<string, DateTime?> ParseWindowsExport()
    {
        var regex = new Regex("(?<date>\\d{4}-\\d{2}-\\d{2}) (?<time>\\d{2}\\.\\d{2}\\.\\d{2})", RegexOptions.Compiled);
        return fileName =>
        {
            var match = regex.Match(fileName);
            if (!match.Success)
            {
                return null;
            }

            if (DateTime.TryParseExact(match.Groups["date"].Value, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var date) &&
                DateTime.TryParseExact(match.Groups["time"].Value, "HH.mm.ss", CultureInfo.InvariantCulture, DateTimeStyles.None, out var time))
            {
                return date.Date + time.TimeOfDay;
            }

            return null;
        };
    }

    private static Func<string, DateTime?> ParseGenericDatePrefix()
    {
        var regex = new Regex("(?<date>\\d{4})[-_](?<month>\\d{2})[-_](?<day>\\d{2})(?:[-_ ](?<time>\\d{2}[\\.-]\\d{2}[\\.-]\\d{2}))?", RegexOptions.IgnoreCase | RegexOptions.Compiled);
        return fileName =>
        {
            var match = regex.Match(fileName);
            if (!match.Success)
            {
                return null;
            }

            var datePart = $"{match.Groups["date"].Value}{match.Groups["month"].Value}{match.Groups["day"].Value}";
            if (!DateTime.TryParseExact(datePart, "yyyyMMdd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var date))
            {
                return null;
            }

            if (!match.Groups["time"].Success)
            {
                return date;
            }

            var timeToken = match.Groups["time"].Value.Replace('.', ':');
            if (DateTime.TryParseExact(timeToken, "HH:mm:ss", CultureInfo.InvariantCulture, DateTimeStyles.None, out var time))
            {
                return date.Date + time.TimeOfDay;
            }

            return date;
        };
    }
}
