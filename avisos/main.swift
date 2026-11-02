// CacaSN Avisos: notificação do macOS que abre um link/arquivo ao ser clicada.
// Uso: "CacaSN Avisos.app/Contents/MacOS/CacaSNAvisos" <titulo> <texto> <link>
import AppKit
import UserNotifications

final class Delegado: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    var clicado = false

    func applicationDidFinishLaunching(_ n: Notification) {
        let central = UNUserNotificationCenter.current()
        central.delegate = self
        let args = Array(CommandLine.arguments.dropFirst())
        guard args.count >= 3 else {
            // relançado pelo clique: a resposta chega no delegate; sai se nada vier
            DispatchQueue.main.asyncAfter(deadline: .now() + 5) { if !self.clicado { NSApp.terminate(nil) } }
            return
        }
        central.requestAuthorization(options: [.alert, .sound]) { ok, _ in
            guard ok else { DispatchQueue.main.async { NSApp.terminate(nil) }; return }
            let c = UNMutableNotificationContent()
            c.title = args[0]
            c.body = args[1]
            c.sound = UNNotificationSound(named: UNNotificationSoundName("Glass"))
            c.userInfo = ["link": args[2]]
            central.add(UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil)) { _ in
                // fica vivo um tempo para receber o clique; depois disso o clique relança o app
                DispatchQueue.main.asyncAfter(deadline: .now() + 600) { NSApp.terminate(nil) }
            }
        }
    }

    func userNotificationCenter(_ c: UNUserNotificationCenter, willPresent n: UNNotification,
                                withCompletionHandler h: @escaping (UNNotificationPresentationOptions) -> Void) {
        h([.banner, .sound, .list])
    }

    func userNotificationCenter(_ c: UNUserNotificationCenter, didReceive r: UNNotificationResponse,
                                withCompletionHandler h: @escaping () -> Void) {
        clicado = true
        if let s = r.notification.request.content.userInfo["link"] as? String {
            let url = s.contains("://") ? URL(string: s) : URL(fileURLWithPath: s)
            if let url { NSWorkspace.shared.open(url) }
        }
        h()
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) { NSApp.terminate(nil) }
    }
}

let app = NSApplication.shared
let delegado = Delegado()
app.delegate = delegado
app.setActivationPolicy(.prohibited)
app.run()
