namespace PhotoRepair.Core;

public sealed record RepairPlanItem(
    MediaRecord Record,
    RepairMethod Method,
    DateTimeOffset? ProposedValue,
    string Before,
    string After,
    bool Applicable,
    string SkipReason)
{
    public string Path => Record.Path;
    public string Name => Record.Name;
}

public sealed record RepairPreview(
    IReadOnlyList<RepairPlanItem> Items,
    IReadOnlyList<RepairPlanItem> Examples)
{
    public int SelectedCount => Items.Count;
    public int ApplicableCount => Items.Count(item => item.Applicable);
    public int SkippedCount => SelectedCount - ApplicableCount;
}

public static class RepairPlanner
{
    public static RepairMethod FindMethod(string id) =>
        MediaRules.RepairMethods.FirstOrDefault(method => method.Id == id)
        ?? throw new ArgumentException($"Unknown repair method: {id}", nameof(id));

    public static RepairPlanItem Plan(MediaRecord record, RepairMethod method)
    {
        DateTimeOffset? source = SourceValue(record, method.Source);
        string before = DestinationDisplay(record, method.Target);
        if (source is null)
        {
            return new RepairPlanItem(
                record, method, null, before, "", false,
                $"{Title(method.Source)} timestamp is not available.");
        }

        if (method.Target == "taken" &&
            !MediaRules.WritableTakenExtensions.Contains(Path.GetExtension(record.Path).ToLowerInvariant()))
        {
            return new RepairPlanItem(
                record, method, source, before, Timestamps.Format(source.Value), false,
                "Taken At updates are supported only for JPEG files.");
        }

        string after = Timestamps.Format(source.Value);
        DateTimeOffset? destination = DestinationValue(record, method.Target);
        if (destination is not null && Timestamps.Format(destination.Value) == after)
        {
            return new RepairPlanItem(
                record, method, source, before, after, false,
                "Destination already equals the proposed value.");
        }

        // An existing unparsable Taken string is intentionally not treated as a no-op.
        // A confirmed repair may replace it with the selected valid source timestamp.
        return new RepairPlanItem(record, method, source, before, after, true, "");
    }

    public static RepairPreview Preview(
        IEnumerable<MediaRecord> records,
        RepairMethod method,
        int maxExamples = 10)
    {
        int limit = Math.Clamp(maxExamples, 0, 10);
        var items = records.Select(record => Plan(record, method)).ToArray();
        var examples = items.Where(item => item.Applicable).Take(limit).ToArray();
        return new RepairPreview(items, examples);
    }

    private static DateTimeOffset? SourceValue(MediaRecord record, string source) => source switch
    {
        "created" => record.CreatedAt,
        "modified" => record.ModifiedAt,
        "taken" => record.TakenAt,
        "filename" => record.FilenameAt,
        _ => throw new ArgumentException($"Unknown repair source: {source}", nameof(source))
    };

    private static DateTimeOffset? DestinationValue(MediaRecord record, string target) => target switch
    {
        "created" => record.CreatedAt,
        "modified" => record.ModifiedAt,
        "taken" => record.TakenAt,
        _ => throw new ArgumentException($"Unknown repair target: {target}", nameof(target))
    };

    private static string DestinationDisplay(MediaRecord record, string target) => target switch
    {
        "created" => record.Created,
        "modified" => record.Modified,
        "taken" => string.IsNullOrWhiteSpace(record.Taken) ? "(missing)" : record.Taken,
        _ => throw new ArgumentException($"Unknown repair target: {target}", nameof(target))
    };

    private static string Title(string value) => value switch
    {
        "taken" => "Taken",
        "filename" => "Filename",
        "created" => "Created",
        "modified" => "Modified",
        _ => value
    };
}
