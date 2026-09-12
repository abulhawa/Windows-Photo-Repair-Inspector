using System.Text.Json;
using PhotoRepair.Core;

namespace PhotoRepair.Core.Tests;

public sealed class ContractTests
{
    private static JsonElement Contract => JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "behavior-contract.json"))).RootElement;
    public static IEnumerable<object[]> Cases(string key) => Contract.GetProperty(key).EnumerateArray().Select(c => new object[] { c });
    private static string S(JsonElement c, string key) => c.GetProperty(key).GetString()!;
    private static string[] Strings(JsonElement c) => c.EnumerateArray().Select(x => x.GetString()!).ToArray();
    private static DateTimeOffset Instant(double seconds) => DateTimeOffset.UnixEpoch.AddSeconds(seconds);

    [Theory, MemberData(nameof(Cases), "filename_parsing_cases")]
    public void Filename(JsonElement c)
    {
        var actual = Timestamps.FromFilename(S(c, "filename"));
        Assert.Equal(S(c, "expected"), actual is { } value ? Timestamps.Format(value) : null);
    }
    [Theory, MemberData(nameof(Cases), "epoch_filename_cases")]
    public void Epoch(JsonElement c)
    {
        var actual = Timestamps.ExtractEpoch(S(c, "filename"));
        Assert.NotNull(actual);
        Assert.Equal(S(c, "expected_token"), actual.Value.Token);
        Assert.Equal(c.GetProperty("expected_local_year").GetInt32(), actual.Value.Timestamp.Year);
    }
    [Theory, MemberData(nameof(Cases), "proposed_taken_cases")]
    public void Proposal(JsonElement c) => Assert.Equal(S(c, "expected"), MediaRules.ProposeTaken(S(c, "created"), S(c, "filename_date"), S(c, "taken")));
    [Theory, MemberData(nameof(Cases), "issue_detection_cases")]
    public void Issues(JsonElement c)
    {
        var taken = c.GetProperty("taken_ts");
        var record = new MediaRecord(S(c, "path"), S(c, "media_type"), 100,
            Instant(c.GetProperty("created_ts").GetDouble()), Instant(c.GetProperty("modified_ts").GetDouble()),
            S(c, "taken"), taken.ValueKind == JsonValueKind.Null ? null : Instant(taken.GetDouble()));
        Assert.Equal(Strings(c.GetProperty("expected_issues")), record.Issues);
    }
    [Theory, MemberData(nameof(Cases), "selection_range_cases")]
    public void Selection(JsonElement c) => Assert.Equal(Strings(c.GetProperty("expected")), SelectionModel.Range(Strings(c.GetProperty("items")), S(c, "anchor"), S(c, "target")));
    [Fact]
    public void Constants()
    {
        var c = Contract;
        Assert.Equal(Timestamps.DisplayFormat, S(c, "timestamp_display_format"));
        Assert.Equal(MediaRules.ToleranceSeconds, c.GetProperty("timestamp_tolerance_seconds").GetDouble());
        Assert.Equal(Strings(c.GetProperty("writable_taken_extensions")), MediaRules.WritableTakenExtensions);
        Assert.Equal(Strings(c.GetProperty("review_filters")), MediaRules.ReviewFilters);
        Assert.Equal(c.GetProperty("repair_methods").EnumerateArray().Select(m => new RepairMethod(S(m, "label"), S(m, "target"), S(m, "source"))), MediaRules.RepairMethods);
        Assert.Equal(MediaRules.BackupDirectory, S(c.GetProperty("safety_invariants"), "backup_directory_name"));
        Assert.True(c.GetProperty("safety_invariants").GetProperty("exclude_backup_directory_from_scan").GetBoolean());
    }
    [Fact]
    public void LocalWallClockRoundTripsWithoutConversion() => Assert.Equal("2024-03-21 17:45:32", Timestamps.Format(Timestamps.Parse("2024-03-21 17:45:32")!.Value));
    [Theory]
    [InlineData(1, false)]
    [InlineData(1.001, true)]
    public void ToleranceBoundary(double delta, bool review)
    {
        var r = new MediaRecord("a.jpg", "image", 0, Instant(1000), Instant(1000), "present", Instant(1000 + delta));
        Assert.Equal(review, r.Issues.Count != 0);
    }
    [Fact]
    public void UnifiedSelectionKeepsOriginalRangeAnchor()
    {
        string[] items = ["a", "b", "c", "d", "e"];
        var model = new SelectionModel();
        model.Click(items, "b", false, false, false);
        model.Click(items, "d", false, true, false);
        model.Click(items, "e", false, true, true);
        Assert.Equal(new[] { "b", "c", "d", "e" }, model.Selected.Order());
        model.Click(items, "c", false, false, true);
        Assert.DoesNotContain("c", model.Selected);
        model.Clear();
        Assert.Empty(model.Selected);
        Assert.Null(model.Anchor);
        model.SelectAll(items);
        Assert.Equal(5, model.Selected.Count);
    }
    [Fact]
    public void FiltersAndNumericSort()
    {
        var a = new MediaRecord(Path.Combine("Pictures", "Trips", "Example Photo.jpg"), "image", 100, Instant(10), Instant(20));
        var b = a with { Path = "movie.mp4", MediaType = "video", SizeBytes = 9 };
        Assert.True(LibraryQuery.MatchesSearch(a, " TRIPS "));
        Assert.True(LibraryQuery.MatchesSearch(a, "example PHOTO"));
        Assert.False(LibraryQuery.MatchesSearch(a, "unrelated"));
        Assert.Equal(new[] { a }, LibraryQuery.Filter([a, b], "", "image", true, "Missing Taken At"));
        Assert.Equal(new[] { b, a }, new[] { a, b }.OrderBy(r => LibraryQuery.SortValue(r, "Size")));
        Assert.DoesNotContain(a.Name, a.Location);
        Assert.Equal("image", MediaRules.Classify("a.TIFF"));
        Assert.DoesNotContain(".tiff", MediaRules.WritableTakenExtensions);
    }
}

