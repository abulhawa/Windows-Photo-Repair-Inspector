using System;
using System.Collections.Concurrent;
using System.IO;
using System.Text;
using System.Threading.Tasks;

namespace PhotoRepairInspector.Services;

public sealed class ActionLogger : IDisposable
{
    private readonly BlockingCollection<string> _queue = new();
    private readonly Task _worker;
    private readonly string _logFilePath;

    public ActionLogger(string logFilePath)
    {
        _logFilePath = logFilePath;
        Directory.CreateDirectory(Path.GetDirectoryName(_logFilePath)!);
        _worker = Task.Run(ProcessQueueAsync);
    }

    public void Log(string message)
    {
        var line = $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} {message}";
        try
        {
            _queue.Add(line);
        }
        catch (InvalidOperationException)
        {
            // queue completed
        }
    }

    private async Task ProcessQueueAsync()
    {
        await using var stream = new FileStream(_logFilePath, FileMode.Append, FileAccess.Write, FileShare.Read);
        await using var writer = new StreamWriter(stream, new UTF8Encoding(false));
        foreach (var line in _queue.GetConsumingEnumerable())
        {
            await writer.WriteLineAsync(line);
            await writer.FlushAsync();
        }
    }

    public void Dispose()
    {
        _queue.CompleteAdding();
        try
        {
            _worker.Wait(TimeSpan.FromSeconds(2));
        }
        catch (AggregateException)
        {
            // swallow worker exceptions on shutdown
        }
    }
}
