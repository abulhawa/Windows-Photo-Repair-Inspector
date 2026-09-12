using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Media.Imaging;
using PhotoRepair.Core;

namespace PhotoRepair.Windows;

public sealed class MetadataReader
{
    public string? ReadTaken(string path)
    {
        try
        {
            // WPF's decoder is a managed WIC adapter. DelayCreation avoids decoding
            // image pixels; the stream is read-only and never passed to an encoder.
            using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            var decoder = BitmapDecoder.Create(stream, BitmapCreateOptions.DelayCreation, BitmapCacheOption.None);
            if (decoder.Frames[0].Metadata is not BitmapMetadata metadata) return null;
            string[] roots = ["/app1/ifd", "/ifd"];
            foreach (string root in roots)
            {
                foreach (string branch in new[] { root + "/exif", root })
                {
                    foreach (int tag in new[] { 36867, 36868, 306 })
                    {
                        object? value;
                        try { value = metadata.GetQuery($"{branch}/{{ushort={tag}}}"); }
                        catch (Exception ex) when (IsReadFailure(ex)) { continue; }
                        string? text = value switch { string s => s, byte[] b when b.All(x => x < 128) => Encoding.ASCII.GetString(b), _ => null };
                        text = text?.Trim().TrimEnd('\0');
                        if (string.IsNullOrEmpty(text)) continue;
                        // Preserve the reference's display even for an invalid EXIF date;
                        // the separately parsed instant remains null in that case.
                        int replaced = 0;
                        return string.Concat(text.Select(c => c == ':' && replaced++ < 2 ? '-' : c));
                    }
                }
            }
            return null;
        }
        catch (Exception ex) when (IsReadFailure(ex)) { return null; }
    }

    internal static bool IsReadFailure(Exception ex) => ex is IOException or UnauthorizedAccessException
        or ArgumentException or NotSupportedException or COMException or InvalidOperationException;

    public MediaRecord ReadFile(string path)
    {
        var file = new FileInfo(path);
        long length = file.Length; // Throws for disappeared/inaccessible files; scanner isolates it.
        string type = MediaRules.Classify(path);
        string taken = type == "image" ? ReadTaken(path) ?? "" : "";
        return new MediaRecord(file.FullName, type, length,
            new DateTimeOffset(file.CreationTimeUtc), new DateTimeOffset(file.LastWriteTimeUtc),
            taken, Timestamps.Parse(taken), Timestamps.FromFilename(file.Name));
    }
}
