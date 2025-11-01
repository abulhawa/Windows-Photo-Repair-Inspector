using System.Collections.Generic;
using System.Linq;

namespace PhotoRepairInspector.Models;

public class MediaGroupInfo
{
    public required string GroupKey { get; init; }
    public required IReadOnlyList<MediaFileInfo> Items { get; init; }

    public bool OnlyCompressed => !Items.Any(x => !x.IsCompressedVariant && x.Source != MediaSource.WhatsApp);
    public bool AllWhatsApp => Items.All(x => x.Source == MediaSource.WhatsApp);
    public int ItemCount => Items.Count;

    public string Summary
    {
        get
        {
            if (OnlyCompressed)
            {
                return "Only compressed copies found";
            }
            if (AllWhatsApp)
            {
                return "All files appear to be WhatsApp copies";
            }
            if (Items.Any(x => x.ProposedAction == MediaActionType.FixDateFromFilename))
            {
                return "Date fix proposed for one or more files";
            }
            return "Review group";
        }
    }
}
