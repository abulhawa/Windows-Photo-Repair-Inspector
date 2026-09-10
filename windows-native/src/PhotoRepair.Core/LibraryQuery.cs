namespace PhotoRepair.Core;

public static class LibraryQuery
{
    public static bool MatchesSearch(MediaRecord record, string query) =>
        record.Name.Contains(query.Trim(), StringComparison.OrdinalIgnoreCase) || record.Path.Contains(query.Trim(), StringComparison.OrdinalIgnoreCase);

    public static IEnumerable<MediaRecord> Filter(IEnumerable<MediaRecord> records, string search, string media, bool review, string issue) =>
        records.Where(r => MatchesSearch(r, search) && (media == "All" || r.MediaType == media)
            && (!review || r.Issues.Count > 0) && (issue == "All review items" || r.Issues.Contains(issue)));

    public static IComparable SortValue(MediaRecord r, string column) => column switch
    {
        "File" => r.Name.ToUpperInvariant(), "Type" => r.MediaType, "Size" => r.SizeBytes,
        "Created" => r.CreatedAt, "Modified" => r.ModifiedAt,
        "Taken At" => (r.TakenAt is null, r.TakenAt ?? DateTimeOffset.MinValue),
        "Filename Date" => (r.FilenameAt is null, r.FilenameAt ?? DateTimeOffset.MinValue),
        "Location" => r.Location.ToUpperInvariant(), "Review reason" => r.ReviewReason.ToUpperInvariant(),
        _ => throw new ArgumentException("Unknown column", nameof(column))
    };
}
