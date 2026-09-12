namespace PhotoRepair.Core;

public sealed class SelectionModel
{
    private readonly HashSet<string> selected = new(StringComparer.Ordinal);
    public IReadOnlySet<string> Selected => selected;
    public string? Anchor { get; private set; }
    public static IReadOnlyList<string> Range(IReadOnlyList<string> items, string? anchor, string target)
    {
        var list = items.ToList();
        int start = anchor is null ? -1 : list.IndexOf(anchor), end = list.IndexOf(target);
        if (end < 0) return [];
        if (start < 0) return [target];
        return list.GetRange(Math.Min(start, end), Math.Abs(end - start) + 1);
    }
    public void Clear() { selected.Clear(); Anchor = null; }
    public void SelectAll(IReadOnlyList<string> items) { Clear(); selected.UnionWith(items); Anchor = items.FirstOrDefault(); }
    public void Click(IReadOnlyList<string> items, string target, bool ctrl, bool shift, bool checkbox)
    {
        if (!items.Contains(target)) return;
        if (shift && Anchor is not null)
        {
            if (!ctrl || checkbox) selected.Clear();
            selected.UnionWith(Range(items, Anchor, target));
        }
        else if (ctrl || checkbox)
        {
            if (!selected.Remove(target)) selected.Add(target);
            if (!checkbox || Anchor is null) Anchor = target;
        }
        else { selected.Clear(); selected.Add(target); Anchor = target; }
    }
}
