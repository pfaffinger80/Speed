Imports System.Diagnostics
Imports System.IO
Imports System.Drawing
Imports System.Windows.Forms

Public Class Form1
    ' --- UI ELEMENTE (Werden dynamisch erzeugt) ---
    Private WithEvents txtInput As TextBox
    Private WithEvents btnBrowse As Button
    Private WithEvents btnStart As Button
    Private WithEvents txtOutput As TextBox

    ' Variable für den laufenden Python-Prozess
    Private pythonProcess As Process

    ' --- FORMULAR WIRD GELADEN (Oberfläche aufbauen) ---
    Private Sub Form1_Load(sender As Object, e As EventArgs) Handles MyBase.Load
        Me.Text = "Verkehrstracking Launcher Pro"
        Me.Size = New Size(650, 500)
        Me.MinimumSize = New Size(400, 300)
        Me.StartPosition = FormStartPosition.CenterScreen

        ' 1. Eingabefeld (TextBox)
        txtInput = New TextBox() With {
            .Location = New Point(20, 20),
            .Size = New Size(470, 25),
            .ReadOnly = True,
            .Anchor = AnchorStyles.Top Or AnchorStyles.Left Or AnchorStyles.Right,
            .Text = "Bitte ein Video über 'Durchsuchen' auswählen..."
        }

        ' 2. Durchsuchen Button
        btnBrowse = New Button() With {
            .Location = New Point(500, 19),
            .Size = New Size(110, 27),
            .Text = "Durchsuchen...",
            .Anchor = AnchorStyles.Top Or AnchorStyles.Right,
            .Cursor = Cursors.Hand
        }

        ' 3. Start Button
        btnStart = New Button() With {
            .Location = New Point(20, 60),
            .Size = New Size(590, 40),
            .Text = "🚀 PROZESS STARTEN",
            .Font = New Font(Me.Font.FontFamily, 10, FontStyle.Bold),
            .BackColor = Color.FromArgb(0, 122, 204),
            .ForeColor = Color.White,
            .FlatStyle = FlatStyle.Flat,
            .Anchor = AnchorStyles.Top Or AnchorStyles.Left Or AnchorStyles.Right,
            .Cursor = Cursors.Hand
        }
        btnStart.FlatAppearance.BorderSize = 0

        ' 4. Konsolen-Ausgabe (TextBox)
        txtOutput = New TextBox() With {
            .Location = New Point(20, 120),
            .Size = New Size(590, 310),
            .Multiline = True,
            .ScrollBars = ScrollBars.Vertical,
            .ReadOnly = True,
            .BackColor = Color.FromArgb(30, 30, 30),
            .ForeColor = Color.LightGreen,
            .Font = New Font("Consolas", 10),
            .Anchor = AnchorStyles.Top Or AnchorStyles.Bottom Or AnchorStyles.Left Or AnchorStyles.Right
        }

        ' Alle Elemente dem Formular hinzufügen
        Me.Controls.Add(txtInput)
        Me.Controls.Add(btnBrowse)
        Me.Controls.Add(btnStart)
        Me.Controls.Add(txtOutput)

        AppendLog("Willkommen! Oberfläche erfolgreich generiert.")
        AppendLog("Bereit. Wähle ein Video aus und starte das Skript.")
    End Sub

    ' --- BUTTON: DURCHSUCHEN ---
    Private Sub btnBrowse_Click(sender As Object, e As EventArgs) Handles btnBrowse.Click
        Dim openFileDialog As New OpenFileDialog()
        openFileDialog.Filter = "Videodateien|*.mp4;*.avi;*.mov|Alle Dateien|*.*"
        openFileDialog.Title = "Wähle das Input-Video aus"

        If openFileDialog.ShowDialog() = DialogResult.OK Then
            txtInput.Text = openFileDialog.FileName
            AppendLog($"[SYSTEM] Video ausgewählt: {Path.GetFileName(txtInput.Text)}")
        End If
    End Sub

    ' --- BUTTON: START ---
    Private Sub btnStart_Click(sender As Object, e As EventArgs) Handles btnStart.Click
        ' 1. Prüfen ob ein Video ausgewählt wurde
        If String.IsNullOrWhiteSpace(txtInput.Text) OrElse Not File.Exists(txtInput.Text) Then
            MessageBox.Show("Bitte wähle zuerst ein gültiges Video aus!", "Fehler", MessageBoxButtons.OK, MessageBoxIcon.Warning)
            Return
        End If

        ' 2. Prüfen ob das Python-Skript existiert
        Dim scriptPath As String = "speed.py"
        If Not File.Exists(scriptPath) Then
            MessageBox.Show("Die Datei 'speed.py' wurde nicht gefunden. Bitte lege sie in denselben Ordner wie die kompilierte .exe Datei.", "Fehler", MessageBoxButtons.OK, MessageBoxIcon.Error)
            Return
        End If

        ' 3. ORDNERSTRUKTUR ANLEGEN
        ' Hauptordner "Ergebnisse" erstellen (falls er noch nicht existiert)
        Dim baseOutputDir As String = Path.Combine(Application.StartupPath, "Ergebnisse")
        If Not Directory.Exists(baseOutputDir) Then
            Directory.CreateDirectory(baseOutputDir)
        End If

        ' Einen einzigartigen Unterordner für DIESEN Durchlauf erstellen (Datum + Uhrzeit)
        Dim timestamp As String = DateTime.Now.ToString("yyyy-MM-dd_HH-mm-ss")
        Dim runDir As String = Path.Combine(baseOutputDir, "Lauf_" & timestamp)
        Directory.CreateDirectory(runDir)

        ' Dateipfade für Video und CSV in diesem neuen Ordner definieren
        Dim outVideoPath As String = Path.Combine(runDir, "Tracking_Video.mp4")
        Dim outCsvPath As String = Path.Combine(runDir, "Speed_Log.csv")

        txtOutput.Clear()
        AppendLog("=========================================")
        AppendLog($"[SYSTEM] Erstelle Ausgabe-Ordner: Lauf_{timestamp}")
        AppendLog("=========================================")
        btnStart.Enabled = False
        btnStart.BackColor = Color.Gray

        ' 4. PROZESS KONFIGURIEREN
        pythonProcess = New Process()
        pythonProcess.StartInfo.FileName = "python"

        ' Wir übergeben nun explizit den neuen Video-Pfad und den neuen CSV-Pfad an das Python Skript!
        pythonProcess.StartInfo.Arguments = $"-u ""{scriptPath}"" --source ""{txtInput.Text}"" --output ""{outVideoPath}"" --log ""{outCsvPath}"""

        ' Hintergrundausführung
        pythonProcess.StartInfo.UseShellExecute = False
        pythonProcess.StartInfo.RedirectStandardOutput = True
        pythonProcess.StartInfo.RedirectStandardError = True
        pythonProcess.StartInfo.CreateNoWindow = True

        ' Events verknüpfen
        AddHandler pythonProcess.OutputDataReceived, AddressOf OutputHandler
        AddHandler pythonProcess.ErrorDataReceived, AddressOf OutputHandler
        AddHandler pythonProcess.Exited, AddressOf ProcessExited
        pythonProcess.EnableRaisingEvents = True

        Try
            ' Starten
            pythonProcess.Start()
            pythonProcess.BeginOutputReadLine()
            pythonProcess.BeginErrorReadLine()
        Catch ex As Exception
            AppendLog("[FEHLER] Beim Starten von Python: " & ex.Message)
            ResetButton()
        End Try
    End Sub

    ' --- EVENT: LOGS EMPFANGEN ---
    Private Sub OutputHandler(sender As Object, e As DataReceivedEventArgs)
        If Not String.IsNullOrEmpty(e.Data) Then
            AppendLog(e.Data)
        End If
    End Sub

    ' --- EVENT: PROZESS BEENDET ---
    Private Sub ProcessExited(sender As Object, e As EventArgs)
        AppendLog("=========================================")
        AppendLog("[SYSTEM] --- Prozess erfolgreich beendet ---")
        AppendLog("=========================================")
        ResetButton()
    End Sub

    ' --- HILFSFUNKTION: TEXT SICHER SCHREIBEN ---
    Private Sub AppendLog(text As String)
        If txtOutput.InvokeRequired Then
            txtOutput.Invoke(New Action(Of String)(AddressOf AppendLog), text)
        Else
            txtOutput.AppendText(text & Environment.NewLine)
            txtOutput.ScrollToCaret() ' Automatisch mitscrollen
        End If
    End Sub

    ' --- HILFSFUNKTION: BUTTON RESET ---
    Private Sub ResetButton()
        If btnStart.InvokeRequired Then
            btnStart.Invoke(New Action(AddressOf ResetButton))
        Else
            btnStart.Enabled = True
            btnStart.BackColor = Color.FromArgb(0, 122, 204)
        End If
    End Sub

    ' --- SICHERHEIT: PROZESS BEENDEN WENN FENSTER GESCHLOSSEN WIRD ---
    Private Sub Form1_FormClosing(sender As Object, e As FormClosingEventArgs) Handles MyBase.FormClosing
        If pythonProcess IsNot Nothing AndAlso Not pythonProcess.HasExited Then
            Try
                pythonProcess.Kill()
            Catch ex As Exception
                ' Fehler ignorieren, falls der Prozess bereits in der gleichen Millisekunde beendet wurde
            End Try
        End If
    End Sub
End Class
