using System.Buffers.Binary;
using System.Globalization;
using System.IO;
using System.Text;
using PhotoRepair.Core;

namespace PhotoRepair.Windows;

public interface ITakenMetadataWriter
{
    void WriteTaken(string path, DateTimeOffset timestamp);
}

public sealed class TakenMetadataWriter : ITakenMetadataWriter
{
    private const ushort DateTimeTag = 0x0132;
    private const ushort ExifIfdPointerTag = 0x8769;
    private const ushort DateTimeOriginalTag = 0x9003;
    private const ushort DateTimeDigitizedTag = 0x9004;

    public void WriteTaken(string path, DateTimeOffset timestamp)
    {
        string extension = Path.GetExtension(path).ToLowerInvariant();
        if (!MediaRules.WritableTakenExtensions.Contains(extension))
            throw new InvalidOperationException("Taken At updates are supported only for JPEG files.");

        using var stream = new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None);
        JpegLayout layout = InspectJpeg(stream);
        byte[] replacement;
        long replaceOffset;
        int replaceLength;

        if (!layout.HasExif)
        {
            replacement = BuildMinimalExifSegment(timestamp);
            replaceOffset = layout.InsertOffset;
            replaceLength = 0;
        }
        else
        {
            stream.Position = layout.ExifMarkerOffset;
            byte[] oldSegment = new byte[layout.ExifSegmentBytes];
            stream.ReadExactly(oldSegment);
            replacement = RebuildExifSegment(oldSegment, timestamp);
            replaceOffset = layout.ExifMarkerOffset;
            replaceLength = layout.ExifSegmentBytes;
        }

        ReplaceRange(stream, replaceOffset, replaceLength, replacement);
        stream.Flush(flushToDisk: true);
    }

    private static byte[] RebuildExifSegment(byte[] segment, DateTimeOffset timestamp)
    {
        if (segment.Length < 18 || segment[0] != 0xFF || segment[1] != 0xE1)
            throw new InvalidDataException("Existing EXIF APP1 segment is malformed.");

        int declaredLength = (segment[2] << 8) | segment[3];
        if (declaredLength < 8 || declaredLength + 2 != segment.Length)
            throw new InvalidDataException("Existing EXIF APP1 length is invalid.");
        if (!segment.AsSpan(4, 6).SequenceEqual("Exif\0\0"u8))
            throw new InvalidDataException("APP1 segment does not contain EXIF metadata.");

        const int tiffStart = 10;
        ReadOnlySpan<byte> tiff = segment.AsSpan(tiffStart);
        if (tiff.Length < 8)
            throw new InvalidDataException("EXIF TIFF header is truncated.");

        bool littleEndian = tiff[0] == (byte)'I' && tiff[1] == (byte)'I';
        bool bigEndian = tiff[0] == (byte)'M' && tiff[1] == (byte)'M';
        if (!littleEndian && !bigEndian)
            throw new InvalidDataException("EXIF byte order is invalid.");
        if (ReadUInt16(tiff, 2, littleEndian) != 42)
            throw new InvalidDataException("EXIF TIFF magic is invalid.");

        uint ifd0Offset = ReadUInt32(tiff, 4, littleEndian);
        IfdTable ifd0 = ParseIfd(tiff, ifd0Offset, littleEndian);
        uint exifOffset = 0;
        IfdEntry? exifPointer = ifd0.Entries.FirstOrDefault(entry => entry.Tag == ExifIfdPointerTag);
        if (exifPointer is not null)
        {
            ushort type = ReadUInt16(exifPointer.Raw, 2, littleEndian);
            uint count = ReadUInt32(exifPointer.Raw, 4, littleEndian);
            if (type != 4 || count != 1)
                throw new InvalidDataException("EXIF IFD pointer has an unsupported representation.");
            exifOffset = ReadUInt32(exifPointer.Raw, 8, littleEndian);
        }

        IfdTable exifIfd = exifOffset == 0
            ? new IfdTable([], 0)
            : ParseIfd(tiff, exifOffset, littleEndian);

        List<IfdEntry> ifd0Entries = ifd0.Entries
            .Where(entry => entry.Tag is not DateTimeTag and not ExifIfdPointerTag)
            .Select(CloneEntry)
            .ToList();
        List<IfdEntry> exifEntries = exifIfd.Entries
            .Where(entry => entry.Tag is not DateTimeOriginalTag and not DateTimeDigitizedTag)
            .Select(CloneEntry)
            .ToList();

        int oldTiffLength = tiff.Length;
        uint newIfd0Offset = checked((uint)Align2(oldTiffLength));
        int ifd0Count = checked(ifd0Entries.Count + 2);
        int newIfd0Size = checked(2 + ifd0Count * 12 + 4);
        uint newExifOffset = checked((uint)Align2(checked((int)newIfd0Offset + newIfd0Size)));
        int exifCount = checked(exifEntries.Count + 2);
        int newExifSize = checked(2 + exifCount * 12 + 4);
        uint dateOffset = checked((uint)Align2(checked((int)newExifOffset + newExifSize)));
        int newTiffLength = checked((int)dateOffset + 20);

        int newPayloadLength = checked(6 + newTiffLength);
        int newJpegLength = checked(newPayloadLength + 2);
        if (newJpegLength > ushort.MaxValue)
            throw new InvalidDataException("Updated EXIF metadata exceeds the JPEG APP1 size limit.");

        byte[] rebuilt = new byte[checked(newPayloadLength + 4)];
        rebuilt[0] = 0xFF;
        rebuilt[1] = 0xE1;
        rebuilt[2] = (byte)(newJpegLength >> 8);
        rebuilt[3] = (byte)newJpegLength;
        "Exif\0\0"u8.CopyTo(rebuilt.AsSpan(4, 6));
        segment.AsSpan(tiffStart).CopyTo(rebuilt.AsSpan(tiffStart));

        Span<byte> rebuiltTiff = rebuilt.AsSpan(tiffStart);
        WriteUInt32(rebuiltTiff, 4, newIfd0Offset, littleEndian);

        byte[] date = Encoding.ASCII.GetBytes(ExifValue(timestamp) + "\0");
        if (date.Length != 20)
            throw new InvalidOperationException("Unexpected EXIF timestamp length.");

        ifd0Entries.Add(BuildEntry(DateTimeTag, 2, 20, dateOffset, littleEndian));
        ifd0Entries.Add(BuildEntry(ExifIfdPointerTag, 4, 1, newExifOffset, littleEndian));
        exifEntries.Add(BuildEntry(DateTimeOriginalTag, 2, 20, dateOffset, littleEndian));
        exifEntries.Add(BuildEntry(DateTimeDigitizedTag, 2, 20, dateOffset, littleEndian));

        WriteIfd(rebuiltTiff, newIfd0Offset, ifd0Entries.OrderBy(entry => entry.Tag).ToArray(), ifd0.NextOffset, littleEndian);
        WriteIfd(rebuiltTiff, newExifOffset, exifEntries.OrderBy(entry => entry.Tag).ToArray(), exifIfd.NextOffset, littleEndian);
        date.CopyTo(rebuiltTiff.Slice((int)dateOffset, date.Length));
        return rebuilt;
    }

    private static IfdTable ParseIfd(ReadOnlySpan<byte> tiff, uint offset, bool littleEndian)
    {
        if (offset > int.MaxValue || offset + 2u > tiff.Length)
            throw new InvalidDataException("EXIF IFD offset is outside the TIFF payload.");

        int position = (int)offset;
        ushort count = ReadUInt16(tiff, position, littleEndian);
        int entriesStart = checked(position + 2);
        int entriesBytes = checked(count * 12);
        int nextOffsetPosition = checked(entriesStart + entriesBytes);
        if (nextOffsetPosition + 4 > tiff.Length)
            throw new InvalidDataException("EXIF IFD table is truncated.");

        List<IfdEntry> entries = new(count);
        for (int index = 0; index < count; index++)
        {
            int entryOffset = checked(entriesStart + index * 12);
            byte[] raw = tiff.Slice(entryOffset, 12).ToArray();
            entries.Add(new IfdEntry(ReadUInt16(raw, 0, littleEndian), raw));
        }

        uint nextOffset = ReadUInt32(tiff, nextOffsetPosition, littleEndian);
        return new IfdTable(entries, nextOffset);
    }

    private static void WriteIfd(
        Span<byte> tiff,
        uint offset,
        IReadOnlyList<IfdEntry> entries,
        uint nextOffset,
        bool littleEndian)
    {
        if (entries.Count > ushort.MaxValue || offset > int.MaxValue)
            throw new InvalidDataException("Updated EXIF IFD is too large.");

        int position = (int)offset;
        int required = checked(2 + entries.Count * 12 + 4);
        if (position + required > tiff.Length)
            throw new InvalidDataException("Updated EXIF IFD does not fit in the TIFF payload.");

        WriteUInt16(tiff, position, (ushort)entries.Count, littleEndian);
        int cursor = position + 2;
        foreach (IfdEntry entry in entries)
        {
            entry.Raw.CopyTo(tiff.Slice(cursor, 12));
            cursor += 12;
        }
        WriteUInt32(tiff, cursor, nextOffset, littleEndian);
    }

    private static IfdEntry BuildEntry(ushort tag, ushort type, uint count, uint valueOrOffset, bool littleEndian)
    {
        byte[] raw = new byte[12];
        WriteUInt16(raw, 0, tag, littleEndian);
        WriteUInt16(raw, 2, type, littleEndian);
        WriteUInt32(raw, 4, count, littleEndian);
        WriteUInt32(raw, 8, valueOrOffset, littleEndian);
        return new IfdEntry(tag, raw);
    }

    private static IfdEntry CloneEntry(IfdEntry entry) => new(entry.Tag, (byte[])entry.Raw.Clone());

    private static void ReplaceRange(FileStream stream, long start, int oldLength, byte[] replacement)
    {
        if (start < 0 || oldLength < 0 || start + oldLength > stream.Length)
            throw new InvalidDataException("JPEG replacement range is invalid.");

        long tailStart = checked(start + oldLength);
        long originalLength = stream.Length;
        long tailLength = originalLength - tailStart;
        long delta = replacement.LongLength - oldLength;
        byte[] buffer = new byte[1024 * 1024];

        if (delta > 0)
        {
            stream.SetLength(checked(originalLength + delta));
            long remaining = tailLength;
            while (remaining > 0)
            {
                int count = (int)Math.Min(buffer.Length, remaining);
                long readPosition = checked(tailStart + remaining - count);
                stream.Position = readPosition;
                stream.ReadExactly(buffer.AsSpan(0, count));
                stream.Position = checked(readPosition + delta);
                stream.Write(buffer, 0, count);
                remaining -= count;
            }
        }
        else if (delta < 0)
        {
            long moved = 0;
            while (moved < tailLength)
            {
                int count = (int)Math.Min(buffer.Length, tailLength - moved);
                stream.Position = checked(tailStart + moved);
                stream.ReadExactly(buffer.AsSpan(0, count));
                stream.Position = checked(tailStart + delta + moved);
                stream.Write(buffer, 0, count);
                moved += count;
            }
            stream.SetLength(checked(originalLength + delta));
        }

        stream.Position = start;
        stream.Write(replacement);
    }

    private static byte[] BuildMinimalExifSegment(DateTimeOffset timestamp)
    {
        const uint ifd0Offset = 8;
        const uint exifIfdOffset = 38;
        const uint dateOffset = 68;
        byte[] date = Encoding.ASCII.GetBytes(ExifValue(timestamp) + "\0");
        if (date.Length != 20)
            throw new InvalidOperationException("Unexpected EXIF timestamp length.");

        using var payload = new MemoryStream();
        payload.Write("Exif\0\0"u8);
        using (var writer = new BinaryWriter(payload, Encoding.ASCII, leaveOpen: true))
        {
            writer.Write((byte)'I');
            writer.Write((byte)'I');
            writer.Write((ushort)42);
            writer.Write(ifd0Offset);
            writer.Write((ushort)2);
            WriteEntry(writer, DateTimeTag, 2, 20, dateOffset);
            WriteEntry(writer, ExifIfdPointerTag, 4, 1, exifIfdOffset);
            writer.Write((uint)0);
            writer.Write((ushort)2);
            WriteEntry(writer, DateTimeOriginalTag, 2, 20, dateOffset);
            WriteEntry(writer, DateTimeDigitizedTag, 2, 20, dateOffset);
            writer.Write((uint)0);
            writer.Write(date);
        }

        byte[] body = payload.ToArray();
        int jpegLength = checked(body.Length + 2);
        if (jpegLength > ushort.MaxValue)
            throw new InvalidOperationException("EXIF block is too large.");
        byte[] segment = new byte[body.Length + 4];
        segment[0] = 0xFF;
        segment[1] = 0xE1;
        segment[2] = (byte)(jpegLength >> 8);
        segment[3] = (byte)jpegLength;
        Buffer.BlockCopy(body, 0, segment, 4, body.Length);
        return segment;
    }

    private static void WriteEntry(BinaryWriter writer, ushort tag, ushort type, uint count, uint valueOrOffset)
    {
        writer.Write(tag);
        writer.Write(type);
        writer.Write(count);
        writer.Write(valueOrOffset);
    }

    private static JpegLayout InspectJpeg(FileStream stream)
    {
        stream.Position = 0;
        if (stream.ReadByte() != 0xFF || stream.ReadByte() != 0xD8)
            throw new InvalidDataException("The selected file is not a valid JPEG stream.");

        long position = 2;
        long insertOffset = 2;
        byte[] signature = new byte[6];
        while (position < stream.Length)
        {
            stream.Position = position;
            if (stream.ReadByte() != 0xFF)
                throw new InvalidDataException("JPEG marker structure is invalid before image data.");

            int marker;
            do { marker = stream.ReadByte(); } while (marker == 0xFF);
            if (marker < 0)
                throw new EndOfStreamException("Unexpected end of JPEG stream.");
            if (marker is 0xD9 or 0xDA)
                break;
            if (marker == 0x00)
                throw new InvalidDataException("Unexpected stuffed JPEG marker before image data.");

            if (marker == 0x01 || marker is >= 0xD0 and <= 0xD7)
            {
                position = stream.Position;
                continue;
            }

            int high = stream.ReadByte();
            int low = stream.ReadByte();
            if (high < 0 || low < 0)
                throw new EndOfStreamException("Unexpected end of JPEG segment.");
            int length = (high << 8) | low;
            if (length < 2)
                throw new InvalidDataException("JPEG segment has an invalid length.");

            long payloadStart = stream.Position;
            long next = checked(payloadStart + length - 2L);
            if (next > stream.Length)
                throw new InvalidDataException("JPEG segment extends beyond the file.");

            if (marker == 0xE1 && length >= 8)
            {
                stream.ReadExactly(signature);
                if (signature.AsSpan().SequenceEqual("Exif\0\0"u8))
                    return new JpegLayout(true, insertOffset, position, checked(length + 2));
            }

            if (marker == 0xE0 && position == insertOffset)
                insertOffset = next;
            position = next;
        }

        return new JpegLayout(false, insertOffset, 0, 0);
    }

    private static string ExifValue(DateTimeOffset timestamp) =>
        timestamp.ToLocalTime().ToString("yyyy:MM:dd HH:mm:ss", CultureInfo.InvariantCulture);

    private static int Align2(int value) => checked((value + 1) & ~1);

    private static ushort ReadUInt16(ReadOnlySpan<byte> data, int offset, bool littleEndian)
    {
        if (offset < 0 || offset + 2 > data.Length)
            throw new InvalidDataException("EXIF value is out of bounds.");
        return littleEndian
            ? BinaryPrimitives.ReadUInt16LittleEndian(data.Slice(offset, 2))
            : BinaryPrimitives.ReadUInt16BigEndian(data.Slice(offset, 2));
    }

    private static uint ReadUInt32(ReadOnlySpan<byte> data, int offset, bool littleEndian)
    {
        if (offset < 0 || offset + 4 > data.Length)
            throw new InvalidDataException("EXIF value is out of bounds.");
        return littleEndian
            ? BinaryPrimitives.ReadUInt32LittleEndian(data.Slice(offset, 4))
            : BinaryPrimitives.ReadUInt32BigEndian(data.Slice(offset, 4));
    }

    private static void WriteUInt16(Span<byte> data, int offset, ushort value, bool littleEndian)
    {
        if (offset < 0 || offset + 2 > data.Length)
            throw new InvalidDataException("EXIF value is out of bounds.");
        if (littleEndian)
            BinaryPrimitives.WriteUInt16LittleEndian(data.Slice(offset, 2), value);
        else
            BinaryPrimitives.WriteUInt16BigEndian(data.Slice(offset, 2), value);
    }

    private static void WriteUInt32(Span<byte> data, int offset, uint value, bool littleEndian)
    {
        if (offset < 0 || offset + 4 > data.Length)
            throw new InvalidDataException("EXIF value is out of bounds.");
        if (littleEndian)
            BinaryPrimitives.WriteUInt32LittleEndian(data.Slice(offset, 4), value);
        else
            BinaryPrimitives.WriteUInt32BigEndian(data.Slice(offset, 4), value);
    }

    private sealed record IfdEntry(ushort Tag, byte[] Raw);
    private sealed record IfdTable(IReadOnlyList<IfdEntry> Entries, uint NextOffset);
    private readonly record struct JpegLayout(
        bool HasExif,
        long InsertOffset,
        long ExifMarkerOffset,
        int ExifSegmentBytes);
}
