using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows.Forms;

[assembly: AssemblyTitle("Synthia AI")]
[assembly: AssemblyDescription("Synthia · Personal Local AI Command Bridge")]
[assembly: AssemblyProduct("Synthia AI")]
[assembly: AssemblyVersion("0.1.0.0")]

static class Program
{
    [DllImport("shell32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern int SetCurrentProcessExplicitAppUserModelID(string AppID);

    [STAThread]
    static int Main(string[] args)
    {
        try { SetCurrentProcessExplicitAppUserModelID("Synthia.CommandBridge.App"); } catch { }

        string root = AppDomain.CurrentDomain.BaseDirectory;
        string runtimeJson = Path.Combine(root, "synthia_data", "runtime.json");

        // যদি Synthia আগে থেকেই ব্যাকগ্রাউন্ডে (System Tray) চালু থাকে, তাহলে উইন্ডোটি সামনে নিয়ে আসো
        if (File.Exists(runtimeJson) && args.Length == 0)
        {
            try
            {
                string json = File.ReadAllText(runtimeJson, Encoding.UTF8);
                Match pm = Regex.Match(json, "\"port\"\\s*:\\s*(\\d+)");
                Match tm = Regex.Match(json, "\"token\"\\s*:\\s*\"([^\"]+)\"");
                if (pm.Success && tm.Success)
                {
                    string url = "http://127.0.0.1:" + pm.Groups[1].Value + "/api/show?token=" + Uri.EscapeDataString(tm.Groups[1].Value);
                    HttpWebRequest req = (HttpWebRequest)WebRequest.Create(url);
                    req.Method = "POST";
                    req.ContentLength = 0;
                    req.Timeout = 1500;
                    using (HttpWebResponse resp = (HttpWebResponse)req.GetResponse())
                    {
                        if ((int)resp.StatusCode == 200)
                            return 0;
                    }
                }
            }
            catch
            {
                // পুরনো runtime.json বা সার্ভার বন্ধ — নিচে নতুন করে চালু হবে
            }
        }

        string pythonw = Path.Combine(root, ".venv", "Scripts", "pythonw.exe");
        if (!File.Exists(pythonw))
        {
            MessageBox.Show(
                "Synthia চালু করার জন্য .venv\\Scripts\\pythonw.exe পাওয়া যায়নি।\nঅনুগ্রহ করে সেটআপ চেক করুন।",
                "Synthia AI",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            );
            return 1;
        }

        StringBuilder argStr = new StringBuilder("-m synthia.main");
        foreach (string a in args)
        {
            argStr.Append(" \"");
            argStr.Append(a.Replace("\"", "\\\""));
            argStr.Append("\"");
        }

        ProcessStartInfo psi = new ProcessStartInfo();
        psi.FileName = pythonw;
        psi.Arguments = argStr.ToString();
        psi.WorkingDirectory = root;
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;
        psi.EnvironmentVariables["PYTHONUTF8"] = "1";

        Process.Start(psi);
        return 0;
    }
}
