import AppKit
import UniformTypeIdentifiers
import WebKit

final class LibraryApp: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate, NSWindowDelegate, WKScriptMessageHandlerWithReply {
    var window: NSWindow!
    var web: WKWebView!
    var server: Process?
    let key = UUID().uuidString + UUID().uuidString
    var origin: URL?
    var terminating = false

    private struct ExportDownload {
        let download: WKDownload
        var destination: URL?
        let retryDestination: URL?
        var observation: NSKeyValueObservation?
    }
    private var exportDownloads: [ObjectIdentifier: ExportDownload] = [:]
    private let downloadSizes = ByteCountFormatter()

    func applicationDidFinishLaunching(_ notification: Notification) {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        config.userContentController.addScriptMessageHandler(self, contentWorld: .page, name: "backupCheck")
        web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = self
        web.uiDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1220, height: 800), styleMask: [.titled,.closable,.miniaturizable,.resizable], backing: .buffered, defer: false)
        window.minSize = NSSize(width: 660, height: 480)
        let name = Bundle.main.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String ?? "勋的软件"
        window.title = name
        window.delegate = self
        window.contentView = web
        window.center()
        window.setFrameAutosaveName("PaperLibraryMain")
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        let menu = NSMenu()
        let appItem = NSMenuItem(); menu.addItem(appItem)
        let app = NSMenu(); appItem.submenu = app
        app.addItem(withTitle:"退出" + name,action:#selector(NSApplication.terminate(_:)),keyEquivalent:"q")
        let editItem=NSMenuItem();menu.addItem(editItem)
        let edit=NSMenu(title:"编辑");editItem.submenu=edit
        for (name,action,shortcut) in [("撤销","undo:","z"),("剪切","cut:","x"),("复制","copy:","c"),("粘贴","paste:","v"),("全选","selectAll:","a")] {
            edit.addItem(withTitle:name,action:NSSelectorFromString(action),keyEquivalent:shortcut)
        }
        NSApp.mainMenu=menu
        web.loadHTMLString("<meta charset=utf-8><p style='font:18px -apple-system;margin:50px'>正在打开\(name)…</p>",baseURL:nil)
        startServer()
    }
    func fail(_ message:String) {
        let alert=NSAlert(); alert.messageText="资料库未能打开";alert.informativeText=message;alert.runModal();NSApp.terminate(nil)
    }
    func startServer(){
        guard let res=Bundle.main.resourceURL else{return fail("缺少应用资源。")}
        let data=FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0].appendingPathComponent("ZhijianKeywordLibrary")
        let proc=Process();server=proc;let bundled=data.deletingLastPathComponent().appendingPathComponent("ZhijianKeywordSoftware/runtime/bin/python3");proc.executableURL=FileManager.default.isExecutableFile(atPath:bundled.path) ? bundled : URL(fileURLWithPath:"/usr/bin/python3")
        proc.arguments=["-B","-u",res.appendingPathComponent("server.py").path,"--local","--port","0","--data",data.path]
        var env=ProcessInfo.processInfo.environment;env["PAPER_LOCAL_KEY"]=key;proc.environment=env
        let out=Pipe();proc.standardOutput=out
        // Keeping the pipe open lets the child report its actual listening port.
        proc.terminationHandler={ [weak self] _ in DispatchQueue.main.async {
            guard let self=self,!self.terminating else{return}
            self.fail("本地服务已退出。重新打开应用可继续使用已保存的数据。")
        }}
        do {try proc.run()}catch{return fail(error.localizedDescription)}
        DispatchQueue.global().async { [weak self] in
            let bytes=out.fileHandleForReading.availableData
            let result=String(data:bytes,encoding:.utf8)?.trimmingCharacters(in:.whitespacesAndNewlines) ?? ""
            DispatchQueue.main.async {
                guard let self=self, result.hasPrefix("PORT="),let port=Int(result.dropFirst(5)),let url=URL(string:"http://127.0.0.1:\(port)/") else{return}
                self.origin=url;var req=URLRequest(url:url);req.setValue("Bearer "+self.key,forHTTPHeaderField:"Authorization");self.web.load(req)
            }
        }
    }
    func applicationWillTerminate(_ notification:Notification){terminating=true;if let p=server,p.isRunning{p.terminate()}}
    func applicationShouldTerminateAfterLastWindowClosed(_ sender:NSApplication)->Bool{true}
    func webView(_ view:WKWebView,decidePolicyFor action:WKNavigationAction,decisionHandler:@escaping(WKNavigationActionPolicy)->Void){
        guard let url=action.request.url else{return decisionHandler(.cancel)}
        if url.scheme=="about"{return decisionHandler(.allow)}
        guard let base=origin else{return decisionHandler(.cancel)}
        if url.host==base.host && url.port==base.port && url.scheme=="http"{return decisionHandler(action.shouldPerformDownload ? .download:.allow)}
        if action.navigationType == .linkActivated, ["https","http"].contains(url.scheme ?? ""){NSWorkspace.shared.open(url)}
        decisionHandler(.cancel)
    }
    func webView(_ view:WKWebView,decidePolicyFor response:WKNavigationResponse,decisionHandler:@escaping(WKNavigationResponsePolicy)->Void){
        let attachment=(response.response as? HTTPURLResponse)?.value(forHTTPHeaderField:"Content-Disposition")?.lowercased().hasPrefix("attachment") ?? false
        decisionHandler(attachment ? .download:.allow)
    }
    private func exportRequest(_ download: WKDownload) -> URLRequest? {
        guard let url = download.originalRequest?.url, let base = origin,
              url.scheme == base.scheme, url.host == base.host, url.port == base.port,
              ["/api/export-download", "/api/program-update"].contains(url.path) else { return nil }
        return URLRequest(url: url)
    }

    private func followDownload(_ download: WKDownload, destination: URL? = nil, retrying: URL? = nil) {
        download.delegate = self
        guard exportRequest(download) != nil || destination != nil else { return }
        let id = ObjectIdentifier(download)
        let observer = download.progress.observe(\.completedUnitCount, options: [.new]) { [weak self] _, _ in
            DispatchQueue.main.async { self?.showDownloadProgress() }
        }
        exportDownloads[id] = ExportDownload(download: download, destination: destination,
                                             retryDestination: retrying, observation: observer)
        showDownloadProgress()
    }

    private func showDownloadProgress() {
        let active = exportDownloads.values.filter { $0.destination != nil }
        if active.count > 1 {
            window.subtitle = "正在下载 \(active.count) 个 ZIP"
        } else if let item = active.first {
            let progress = item.download.progress
            let received = downloadSizes.string(fromByteCount: progress.completedUnitCount)
            let total = progress.totalUnitCount
            window.subtitle = total > 0
                ? "正在下载 \(received) / \(downloadSizes.string(fromByteCount: total))"
                : "正在下载 \(received)"
        } else {
            window.subtitle = ""
        }
    }

    func webView(_ view:WKWebView,navigationResponse:WKNavigationResponse,didBecome download:WKDownload){followDownload(download)}
    func webView(_ view:WKWebView,navigationAction:WKNavigationAction,didBecome download:WKDownload){followDownload(download)}
    func download(_ download:WKDownload,decideDestinationUsing response:URLResponse,suggestedFilename:String,completionHandler:@escaping(URL?)->Void){
        let id = ObjectIdentifier(download)
        if exportDownloads[id] != nil, let http = response as? HTTPURLResponse,
           ![200, 206].contains(http.statusCode) || response.mimeType != "application/zip" {
            exportDownloads.removeValue(forKey: id)
            showDownloadProgress()
            completionHandler(nil)
            let alert = NSAlert()
            alert.messageText = "ZIP 暂时无法下载"
            alert.informativeText = http.statusCode == 410 ? "文件已过期，请在「导出记录」重新生成。" :
                "请回到「导出记录」查看文件是否已生成，或重新打开「备份与换机」。"
            alert.beginSheetModal(for: window)
            return
        }
        let previous = exportDownloads[id]?.retryDestination
        let filename: String
        if let previous = previous {
            filename = FileManager.default.fileExists(atPath: previous.path)
                ? previous.deletingPathExtension().lastPathComponent + "-重试.zip"
                : previous.lastPathComponent
        } else {
            filename = suggestedFilename
        }
        chooseDownloadDestination(download, filename: filename, folder: previous?.deletingLastPathComponent(),
                                  completionHandler: completionHandler)
    }

    private func chooseDownloadDestination(_ download: WKDownload, filename: String, folder: URL?,
                                           completionHandler: @escaping (URL?) -> Void) {
        let id = ObjectIdentifier(download)
        let panel = NSSavePanel()
        panel.nameFieldStringValue = filename
        panel.directoryURL = folder
        panel.canCreateDirectories = true
        panel.beginSheetModal(for:window){ [weak self] answer in
            let destination = answer == .OK ? panel.url : nil
            if let self = self, let destination = destination, self.exportDownloads[id] != nil,
               FileManager.default.fileExists(atPath: destination.path) {
                let alert = NSAlert()
                alert.messageText = "请选择新的 ZIP 文件名"
                alert.informativeText = "这个位置已有同名文件。换个名称可以保留原文件。"
                alert.addButton(withTitle: "重新选择")
                alert.addButton(withTitle: "取消下载")
                alert.beginSheetModal(for: self.window) { responseCode in
                    if responseCode == .alertFirstButtonReturn {
                        self.chooseDownloadDestination(download,
                            filename: destination.deletingPathExtension().lastPathComponent + "-副本.zip",
                            folder: destination.deletingLastPathComponent(), completionHandler: completionHandler)
                    } else {
                        self.exportDownloads.removeValue(forKey: id)
                        self.showDownloadProgress()
                        completionHandler(nil)
                    }
                }
                return
            }
            if let destination = destination {
                self?.exportDownloads[id]?.destination = destination
            } else {
                self?.exportDownloads.removeValue(forKey: id)
            }
            self?.showDownloadProgress()
            completionHandler(destination)
        }
    }

    func downloadDidFinish(_ download: WKDownload) {
        let item = exportDownloads.removeValue(forKey: ObjectIdentifier(download))
        showDownloadProgress()
        guard let url = item?.destination, FileManager.default.fileExists(atPath: url.path) else { return }
        let alert = NSAlert()
        alert.messageText = "ZIP 已下载"
        alert.informativeText = url.lastPathComponent
        alert.addButton(withTitle: "在访达中显示")
        alert.addButton(withTitle: "关闭")
        alert.beginSheetModal(for: window) { response in
            if response == .alertFirstButtonReturn {
                NSWorkspace.shared.activateFileViewerSelecting([url])
            }
        }
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        let item = exportDownloads.removeValue(forKey: ObjectIdentifier(download))
        showDownloadProgress()
        let failure = error as NSError
        if failure.domain == NSURLErrorDomain && failure.code == NSURLErrorCancelled { return }
        let request = exportRequest(download)
        guard item != nil || request != nil else {
            NSAlert(error: error).beginSheetModal(for: window)
            return
        }
        let resume = item?.destination == nil ? nil : resumeData
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = "ZIP 下载中断"
        let filename = item?.destination?.lastPathComponent
        let explanation = resume != nil ? "可以继续下载。" :
            request != nil ? "可以重新下载同一份 ZIP。" : "请从「导出记录」重新下载。"
        alert.informativeText = [filename, explanation, failure.localizedDescription].compactMap { $0 }.joined(separator: "\n")
        if resume != nil || request != nil {
            alert.addButton(withTitle: resume != nil ? "继续下载" : "重新下载")
            alert.addButton(withTitle: "关闭")
        } else {
            alert.addButton(withTitle: "关闭")
        }
        alert.beginSheetModal(for: window) { [weak self] response in
            guard let self = self, response == .alertFirstButtonReturn else { return }
            if let resume = resume {
                self.web.resumeDownload(fromResumeData: resume) { next in
                    self.followDownload(next, destination: item?.destination)
                }
            } else if let request = request {
                self.web.startDownload(using: request) { next in
                    self.followDownload(next, retrying: item?.destination)
                }
            }
        }
    }
    func webView(_ view:WKWebView,runOpenPanelWith params:WKOpenPanelParameters,initiatedByFrame frame:WKFrameInfo,completionHandler:@escaping([URL]?)->Void){
        let p=NSOpenPanel();p.canChooseDirectories=false;p.allowsMultipleSelection=params.allowsMultipleSelection
        p.beginSheetModal(for:window){response in completionHandler(response == .OK ? p.urls:nil)}
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage,
                               replyHandler: @escaping (Any?, String?) -> Void) {
        let frame = message.frameInfo
        let source = frame.securityOrigin
        guard message.name == "backupCheck", frame.isMainFrame, let base = origin,
              source.protocol == base.scheme, source.host == base.host, source.port == base.port,
              let endpoint = URL(string: "/api/backup-check-native", relativeTo: base) else {
            replyHandler(nil, "请从勋的软件中打开备份检查。")
            return
        }
        let panel = NSOpenPanel()
        panel.message = "选择勋的软件的备份 ZIP"
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.allowedContentTypes = [.zip]
        panel.beginSheetModal(for: window) { response in
            guard response == .OK, let file = panel.url else {
                replyHandler("{\"cancelled\":true}", nil)
                return
            }
            var request = URLRequest(url: endpoint)
            request.httpMethod = "POST"
            request.setValue("Bearer " + self.key, forHTTPHeaderField: "Authorization")
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try? JSONEncoder().encode(["path": file.path])
            URLSession.shared.dataTask(with: request) { bytes, _, _ in
                DispatchQueue.main.async {
                    if let bytes = bytes, let json = String(data: bytes, encoding: .utf8) {
                        replyHandler(json, nil)
                    } else {
                        replyHandler(nil, "暂时打不开这份备份。请检查文件后重试。")
                    }
                }
            }.resume()
        }
    }
}
let app=NSApplication.shared
let delegate=LibraryApp();app.delegate=delegate;app.setActivationPolicy(.regular);app.run()
