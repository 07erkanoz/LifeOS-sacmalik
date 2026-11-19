import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia
import QtQuick.Dialogs
import QtQuick.Effects

ApplicationWindow {
    id: win
    width: 1180; height: 780
    minimumWidth: 760; minimumHeight: 520
    visible: true
    title: "Saçmalık Odası"
    color: Theme.bg
    // KDE'nin başlık çubuğu yerine uygulamanın kendi başlığı (üst çubuk): sürükle, çift tıkla büyüt
    flags: Qt.Window | Qt.FramelessWindowHint
    readonly property bool maxed: visibility === Window.Maximized || visibility === Window.FullScreen
    function toggleMax() { maxed ? showNormal() : showMaximized() }
    Binding { target: Theme; property: "dark"; value: (cfg.theme || "dark") !== "light" }
    Binding { target: Theme; property: "scale"; value: cfg.fontScale || 1.0 }
    function setScale(v) {
        v = Math.round(Math.min(1.6, Math.max(0.8, v)) * 10) / 10
        var s = cfg; s.fontScale = v; room.saveSettings(s)
        win.status = "Yazı boyutu: %" + Math.round(v * 100)
    }
    Shortcut { sequences: [StandardKey.ZoomIn, "Ctrl+="]; onActivated: win.setScale(Theme.scale + 0.1) }
    Shortcut { sequences: [StandardKey.ZoomOut]; onActivated: win.setScale(Theme.scale - 0.1) }
    Shortcut { sequence: "Ctrl+0"; onActivated: win.setScale(1.0) }
    // CLI'ın bildirdiği kota: "5s %44 · hafta %40"
    function usageText(key) {
        var q = room.quota[key] || [], ws = []
        var order = [["5h", "5s"], ["week", "hafta"]]   // alt pencereler (week:Fable gibi) yalnızca ipucunda
        for (var o = 0; o < order.length; o++)
            for (var i = 0; i < q.length; i++)
                if (q[i].name === order[o][0]) ws.push(order[o][1] + " %" + Math.max(0, 100 - q[i].used))
        // Codex ve Antigravity kendi ekranlarında kalanı yazar: burada da kalan gösterilir
        return ws.length ? ws.join(" · ") + " kaldı" : ""
    }
    function quotaTip(key) {
        var q = room.quota[key] || [], out = []
        for (var i = 0; i < q.length; i++) {
            var parts = q[i].name.split(":")
            var n = (parts[0] === "5h" ? "5 saatlik" : parts[0] === "week" ? "Haftalık" : parts[0])
                    + (parts.length > 1 ? " (" + parts[1] + ")" : "")
            var r = q[i].resets ? new Date(q[i].resets * 1000) : null
            out.push(n + ": %" + Math.max(0, 100 - q[i].used) + " kaldı (%" + q[i].used + " kullanıldı)"
                     + (r ? " · " + Qt.formatDateTime(r, "dd.MM HH:mm") + " yenilenir" : ""))
        }
        return out.join("\n")
    }
    function quotaFull(key) {
        var q = room.quota[key] || []
        for (var i = 0; i < q.length; i++) if ((q[i].name === "5h" || q[i].name === "week") && q[i].used >= 100) return true
        return false
    }
    function togglePanel() { var s = cfg; s.panelOpen = !(cfg.panelOpen !== false); room.saveSettings(s)
                             win.status = s.panelOpen ? "Durum paneli açık" : "Durum paneli gizlendi" }
    Shortcut { sequence: "Ctrl+B"; onActivated: win.togglePanel() }
    function setTheme(t) {
        fade.color = Theme.bg; fadeAnim.restart()       // eski renkten yenisine yumuşak geçiş
        var s = cfg; s.theme = t; room.saveSettings(s)
    }

    property var cfg: room.settings
    function shortModel(m) {
        if (!m) return ""
        return m.replace(/^claude-/, "").replace(/-(\d+)-(\d+)$/, " $1.$2").replace(/^gemini-/, "")
    }
    // ajanın bu sohbetteki rolleri ("Görsel ve sahne · Eleştirmen")
    function rolesOf(key) {
        var r = room.roles
        if (!r.on) return ""
        return r.list.filter(function(x) { return x.agents.indexOf(key) >= 0 }).map(function(x) { return x.title || "rol" }).join(" · ")
    }
    function countWord(n) { return ["hiç", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"][n] || String(n) }
    readonly property var enabledAgents: (cfg.agents || []).filter(function(a) { return a.enabled })
    readonly property string chatTitle: {
        var cs = room.chats
        for (var i = 0; i < cs.length; i++) if (cs[i].id === room.currentChat) return cs[i].title
        return "Yeni sohbet"
    }
    property string status: "Bir konu aç, oda seni dinliyor"

    function agentColor(key) {
        if (key === "user") return Theme.user
        for (var i = 0; i < cfg.agents.length; i++)
            if (cfg.agents[i].key === key) return cfg.agents[i].color
        return Theme.muted
    }
    function indexOfId(id) {
        for (var i = msgs.count - 1; i >= 0; i--)
            if (msgs.get(i).mid === id) return i
        return -1
    }

    // çalışan ajanların balonları en altta durur; biten mesajlar onların üstüne, geliş sırasıyla dizilir
    function firstPending() {
        for (var i = 0; i < msgs.count; i++)
            if (msgs.get(i).pending) return i
        return msgs.count
    }
    ListModel { id: msgs }

    // resim büyük görünüm
    function showImage(path) { viewer.path = path; viewer.open() }
    Popup {
        id: viewer
        property string path: ""
        parent: Overlay.overlay
        x: 0; y: 0; width: parent ? parent.width : 0; height: parent ? parent.height : 0
        modal: true; padding: 0
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: Qt.rgba(0, 0, 0, 0.88) }
        enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 160 } }
        MouseArea { anchors.fill: parent; onClicked: viewer.close() }
        readonly property bool isVid: /\.(mp4|webm|mov|mkv|ogv)$/i.test(path)
        onClosed: bigVid.stop()
        onOpened: if (isVid) bigVid.play()
        Video {
            id: bigVid
            visible: viewer.isVid
            anchors.fill: parent; anchors.margins: 56; anchors.bottomMargin: 72
            source: viewer.isVid ? "file://" + viewer.path : ""
            fillMode: VideoOutput.PreserveAspectFit
            loops: MediaPlayer.Infinite
            MouseArea { anchors.fill: parent
                        onClicked: bigVid.playbackState === MediaPlayer.PlayingState ? bigVid.pause() : bigVid.play() }
        }
        Image {
            id: big
            visible: !viewer.isVid
            anchors.fill: parent; anchors.margins: 56; anchors.bottomMargin: 72
            source: viewer.path && !viewer.isVid ? "file://" + viewer.path : ""
            fillMode: Image.PreserveAspectFit
            asynchronous: true; cache: false; smooth: true; mipmap: true
        }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom; anchors.bottomMargin: 20
            spacing: 10
            Text { anchors.verticalCenter: parent.verticalCenter; color: "#d1d5db"; font.pixelSize: Theme.fs(13)
                   text: viewer.path.replace(/^.*\//, "") + (viewer.isVid ? "  ·  tıkla: oynat/duraklat" : "") + (!viewer.isVid && big.status === Image.Ready ? "  ·  " + big.implicitWidth + "×" + big.implicitHeight : "") }
            GhostButton { text: "↗  Dışarıda aç"; onClicked: Qt.openUrlExternally("file://" + viewer.path) }
            GhostButton { text: "📁  Klasörü aç"; onClicked: Qt.openUrlExternally("file://" + viewer.path.replace(/\/[^\/]*$/, "")) }
            GhostButton { text: "✕  Kapat"; onClicked: viewer.close() }
        }
    }

    // gönderilecek ekler (resim, belge…): ataç, Ctrl+V ya da sürükle-bırak
    property var attachments: []
    function addAttachments(list) {
        var a = attachments.slice()
        for (var i = 0; i < list.length; i++) {
            var p = String(list[i]).replace(/^file:\/\//, "")
            p = decodeURIComponent(p)
            if (p && a.indexOf(p) < 0) a.push(p)
        }
        attachments = a
        if (list.length) win.status = a.length + " ek hazır — mesajla birlikte gidecek"
    }
    function removeAttachment(i) { var a = attachments.slice(); a.splice(i, 1); attachments = a }
    FileDialog {
        id: fileDlg
        title: "Odaya dosya ekle"
        fileMode: FileDialog.OpenFiles
        onAccepted: win.addAttachments(selectedFiles)
    }
    DropArea {
        anchors.fill: parent
        z: 800
        onDropped: function(drop) { if (drop.hasUrls) { win.addAttachments(drop.urls); drop.accept() } }
        Rectangle {
            anchors.fill: parent; anchors.margins: 14; radius: 20
            visible: parent.containsDrag
            color: Qt.rgba(Theme.user.r, Theme.user.g, Theme.user.b, 0.12)
            border.color: Theme.user; border.width: 2
            Text { anchors.centerIn: parent; text: "📎  Bırak, odaya eklensin"; color: Theme.text; font.pixelSize: Theme.fs(20); font.weight: Font.DemiBold }
        }
    }

    // proje klasörü seçici (ajanlar bu klasörde çalışır / üretir)
    property var folderTarget: null   // null => doğrudan kaydet, aksi halde callback
    function pickFolder(cb) { folderTarget = cb || null; folderDlg.open() }
    FolderDialog {
        id: folderDlg
        title: "Proje klasörünü seç"
        currentFolder: "file://" + cfg.workDir
        onAccepted: {
            var path = decodeURIComponent(selectedFolder.toString().replace(/^file:\/\//, ""))
            if (win.folderTarget) win.folderTarget(path)
            else { var s = cfg; s.workDir = path; room.saveSettings(s) }
        }
    }

    Connections {
        target: room
        function onMessageAdded(id, key, name, color, text, pending, time) {
            var item = { mid: id, key: key, name: name, color: color, body: text,
                         pending: pending, ok: true, secs: 0, silent: false, acts: "", media: "", pinned: false,
                         time: time || Qt.formatTime(new Date(), "HH:mm") }
            if (pending) msgs.append(item)
            else msgs.insert(firstPending(), item)
            Qt.callLater(chat.positionViewAtEnd)
        }
        function onRoomReset() { msgs.clear() }
        function onMessagePinned(id, on) {
            var i = indexOfId(id); if (i < 0) return
            msgs.setProperty(i, "pinned", on)
        }
        function onMessageActivity(id, text) {
            var i = indexOfId(id); if (i < 0) return
            msgs.setProperty(i, "acts", text)
        }
        function onMessageMedia(id, paths) {
            var i = indexOfId(id); if (i < 0) return
            msgs.setProperty(i, "media", paths)
            if (i === msgs.count - 1 || chat.atYEnd) Qt.callLater(chat.positionViewAtEnd)
        }
        function onMessageSilent(id) {
            var i = indexOfId(id); if (i < 0) return
            msgs.setProperty(i, "silent", true)
        }
        function onMessageUpdated(id, text) {
            var i = indexOfId(id); if (i < 0) return
            msgs.setProperty(i, "body", text)
            if (chat.atYEnd || i === msgs.count - 1) Qt.callLater(chat.positionViewAtEnd)
        }
        function onMessageDone(id, ok, secs) {
            var i = indexOfId(id); if (i < 0) return
            var was = msgs.get(i).pending
            msgs.setProperty(i, "pending", false)
            msgs.setProperty(i, "ok", ok)
            msgs.setProperty(i, "secs", secs)
            if (was) msgs.setProperty(i, "time", Qt.formatTime(new Date(), "HH:mm"))
            // bitti: hâlâ çalışanların üstüne, geldiği yere taşı
            var t = firstPending()
            if (i < t - 1) msgs.move(i, t - 1, 1)
            else if (i > t) msgs.move(i, t, 1)
            Qt.callLater(chat.positionViewAtEnd)
        }
        function onStatusText(t) { win.status = t }
    }

    // arka plan: koyu zemin, üstte ajan renklerinden çok hafif bir ışık
    Rectangle { anchors.fill: parent; color: Theme.bg; Behavior on color { ColorAnimation { duration: 300 } } }
    Repeater {
        model: [{ c: "#4f8cff", x: 0.35 }, { c: "#d97757", x: 0.62 }, { c: "#10a37f", x: 0.88 }]
        Rectangle {
            width: 620; height: 620; radius: 310
            x: win.width * modelData.x - width / 2; y: -width * 0.62
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0.55; color: "transparent" }
                GradientStop { position: 1; color: Qt.rgba(Qt.color(modelData.c).r, Qt.color(modelData.c).g, Qt.color(modelData.c).b, Theme.glow) }
            }
            layer.enabled: true
            layer.effect: MultiEffect { blurEnabled: true; blur: 1.0; blurMax: 64 }
            SequentialAnimation on opacity {
                loops: Animation.Infinite
                PauseAnimation { duration: index * 1300 }
                NumberAnimation { to: 0.45; duration: 4200; easing.type: Easing.InOutSine }
                NumberAnimation { to: 1; duration: 4200; easing.type: Easing.InOutSine }
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ---------------- sol: katılımcılar ----------------
        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: 250
            color: Theme.panel
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 18
                spacing: 14

                RowLayout {
                    spacing: 10
                    Image {
                        Layout.preferredWidth: 36; Layout.preferredHeight: 36
                        source: "../tr.com.lifeos.Sacmalik.svg"
                        sourceSize: Qt.size(72, 72)
                        smooth: true
                    }
                    ColumnLayout {
                        spacing: 0
                        Text { text: "Saçmalık Odası"; color: Theme.text; font.pixelSize: Theme.fs(16); font.weight: Font.Bold; font.letterSpacing: -0.2 }
                        Text { text: "sen + " + win.countWord(win.cfg.agents.filter(function(a) { return a.enabled }).length) + " yapay zekâ"; color: Theme.muted; font.pixelSize: Theme.fs(11) }
                    }
                }

                Button {
                    id: newBtn
                    Layout.fillWidth: true
                    Layout.topMargin: 4
                    implicitHeight: 40
                    hoverEnabled: true
                    scale: newBtn.down ? 0.97 : 1
                    Behavior on scale { NumberAnimation { duration: 120 } }
                    onClicked: room.newChat()
                    contentItem: Text { text: "＋  Yeni sohbet"; color: "white"; font.pixelSize: Theme.fs(13); font.weight: Font.DemiBold
                                        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    background: Rectangle { radius: 12
                        opacity: newBtn.down ? 0.8 : newBtn.hovered ? 1 : 0.92
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0; color: "#7c4dff" }
                            GradientStop { position: 1; color: "#9b6bff" }
                        }
                        Behavior on opacity { NumberAnimation { duration: 120 } } }
                }

                Text { text: "KATILIMCILAR"; color: Theme.muted; font.pixelSize: Theme.fs(10); font.letterSpacing: 1.5; Layout.topMargin: 4 }

                Participant {
                    Layout.fillWidth: true
                    name: cfg.userName + " (sen)"; tint: Theme.user; sub: "moderatör değil, katılımcı"
                    active: false; online: true; clickable: false
                }
                Repeater {
                    model: cfg.agents
                    Participant {
                        Layout.fillWidth: true
                        name: modelData.name
                        tint: modelData.color
                        sub: !modelData.enabled ? "devre dışı"
                             : !modelData.found ? "komut bulunamadı"
                             : room.speaking.indexOf(modelData.key) >= 0 ? "çalışıyor…"
                             : (modelData.model || "varsayılan model") + (modelData.effort ? " · " + modelData.effort : "")
                        usageLine: win.usageText(modelData.key)
                        usageFull: win.quotaFull(modelData.key)
                        online: modelData.enabled && modelData.found
                        active: room.speaking.indexOf(modelData.key) >= 0
                        clickable: modelData.enabled
                        onClicked: room.poke(modelData.key)
                        ToolTip.visible: hovered; ToolTip.delay: 400; ToolTip.text: "Söz ver" + (usageLine ? "\n\n" + win.quotaTip(modelData.key) : "")
                    }
                }

                Text { text: "SOHBET GEÇMİŞİ"; color: Theme.muted; font.pixelSize: Theme.fs(10); font.letterSpacing: 1.5; Layout.topMargin: 6 }

                ListView {
                    id: history
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 2
                    model: room.chats
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    add: Transition { NumberAnimation { properties: "opacity"; from: 0; to: 1; duration: 220 }
                                      NumberAnimation { properties: "x"; from: -16; duration: 260; easing.type: Easing.OutCubic } }
                    displaced: Transition { NumberAnimation { properties: "y"; duration: 220; easing.type: Easing.OutCubic } }
                    delegate: Rectangle {
                        id: hi
                        required property var modelData
                        readonly property bool current: modelData.id === room.currentChat
                        readonly property bool showTools: (hma.containsMouse || renMa.containsMouse || dma.containsMouse) && !editing
                        property bool editing: false
                        function startEdit() { editing = true; ed.text = modelData.title; ed.forceActiveFocus(); ed.selectAll() }
                        function finishEdit(save) {
                            if (!editing) return
                            editing = false
                            if (save && ed.text.trim() && ed.text.trim() !== modelData.title) room.renameChat(modelData.id, ed.text)
                        }
                        width: history.width
                        height: 48; radius: 10
                        color: current ? Qt.rgba(Theme.user.r, Theme.user.g, Theme.user.b, 0.16)
                             : hma.containsMouse ? Theme.card : "transparent"
                        Behavior on color { ColorAnimation { duration: 120 } }
                        Column {
                            visible: !hi.editing
                            anchors.verticalCenter: parent.verticalCenter
                            x: 10; width: parent.width - 20 - (hi.showTools ? 52 : 0)
                            spacing: 2
                            Text { width: parent.width; text: hi.modelData.title; elide: Text.ElideRight
                                   color: hi.current ? Theme.text : Theme.textDim; font.pixelSize: Theme.fs(12)
                                   font.weight: hi.current ? Font.DemiBold : Font.Normal }
                            Text { text: Qt.formatDateTime(new Date(hi.modelData.updated * 1000), "d MMM HH:mm")
                                         + "  ·  " + hi.modelData.count + " mesaj"
                                   color: Theme.muted; font.pixelSize: Theme.fs(10) }
                        }
                        // yerinde ad değiştirme: Enter kaydeder, Esc vazgeçer
                        TextField {
                            id: ed
                            visible: hi.editing
                            anchors.verticalCenter: parent.verticalCenter
                            x: 6; width: parent.width - 12; height: 34
                            color: Theme.text; font.pixelSize: Theme.fs(12); selectByMouse: true
                            leftPadding: 8
                            background: Rectangle { radius: 8; color: Theme.field; border.color: Theme.user }
                            onAccepted: hi.finishEdit(true)
                            Keys.onEscapePressed: hi.finishEdit(false)
                            onActiveFocusChanged: if (!activeFocus) hi.finishEdit(true)
                        }
                        MouseArea {
                            id: hma
                            anchors.fill: parent
                            visible: !hi.editing
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: if (!hi.current) room.openChat(hi.modelData.id)
                            onDoubleClicked: hi.startEdit()
                        }
                        Row {
                            anchors.right: parent.right; anchors.rightMargin: 6
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 2
                            opacity: hi.showTools ? 1 : 0
                            visible: opacity > 0
                            Behavior on opacity { NumberAnimation { duration: 140 } }
                            Rectangle {
                                width: 24; height: 24; radius: 7
                                color: renMa.containsMouse ? Theme.cardHi : "transparent"
                                Text { anchors.centerIn: parent; text: "✎"; color: renMa.containsMouse ? Theme.text : Theme.muted; font.pixelSize: Theme.fs(13) }
                                MouseArea { id: renMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                            onClicked: hi.startEdit() }
                                ToolTip.visible: renMa.containsMouse; ToolTip.delay: 500; ToolTip.text: "Adını değiştir (ya da çift tıkla)"
                            }
                            Rectangle {
                                width: 24; height: 24; radius: 7
                                color: dma.containsMouse ? Qt.rgba(0.9, 0.28, 0.3, 0.15) : "transparent"
                                Text { anchors.centerIn: parent; text: "🗑"; color: dma.containsMouse ? Theme.danger : Theme.muted; font.pixelSize: Theme.fs(12) }
                                MouseArea { id: dma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                            onClicked: { delDlg.cid = hi.modelData.id; delDlg.title_ = hi.modelData.title; delDlg.open() } }
                                ToolTip.visible: dma.containsMouse; ToolTip.delay: 500; ToolTip.text: "Sohbeti sil"
                            }
                        }
                    }
                    Text {
                        anchors.top: parent.top; anchors.topMargin: 6
                        visible: history.count === 0
                        text: "Henüz kayıtlı sohbet yok"; color: Theme.muted; font.pixelSize: Theme.fs(11)
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    GhostButton { text: "⚙  Ayarlar"; Layout.fillWidth: true; onClicked: settings.open() }
                }
            }
        }

        // ---------------- orta: sohbet ----------------
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // üst bar
            Rectangle {
                Layout.fillWidth: true
                height: 66
                color: Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, 0.6)
                DragHandler { target: null; grabPermissions: PointerHandler.TakeOverForbidden
                              onActiveChanged: if (active) win.startSystemMove() }
                TapHandler { onDoubleTapped: win.toggleMax() }
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.lineSoft }
                RowLayout {
                    id: topRow
                    anchors.fill: parent
                    anchors.leftMargin: 24; anchors.rightMargin: 18
                    spacing: 8
                    readonly property bool tight: width < 1060      // panel açıkken: düğmeler kısalır, başlık sığar
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 120
                        spacing: 2
                        Text { text: win.chatTitle; color: Theme.text; font.pixelSize: Theme.fs(15); font.weight: Font.DemiBold
                               Layout.fillWidth: true; elide: Text.ElideRight }
                        RowLayout {
                            spacing: 7
                            Rectangle {
                                width: 7; height: 7; radius: 3.5
                                color: room.busy ? agentColor(room.speaking[0]) : Theme.ok
                                SequentialAnimation on opacity {
                                    running: room.busy; loops: Animation.Infinite
                                    NumberAnimation { to: 0.25; duration: 500 }
                                    NumberAnimation { to: 1; duration: 500 }
                                }
                            }
                            Text {
                                id: statusTxt
                                color: Theme.muted; font.pixelSize: Theme.fs(12); Layout.fillWidth: true; elide: Text.ElideRight
                                property string target: win.status
                                text: target
                                onTargetChanged: statusAnim.restart()
                                SequentialAnimation {
                                    id: statusAnim
                                    NumberAnimation { target: statusTxt; property: "opacity"; to: 0; duration: 90 }
                                    PropertyAction { target: statusTxt; property: "text"; value: statusTxt.target }
                                    NumberAnimation { target: statusTxt; property: "opacity"; to: 1; duration: 180 }
                                }
                            }
                        }
                    }

                    // Tartışma / Üretim: CLI'ların yazma yetkisi (ajanlara söylenmez, fiziksel kısıt)
                    Rectangle {
                        id: modeSw
                        readonly property bool prod: cfg.production !== false
                        implicitWidth: modeRow.implicitWidth + 8; implicitHeight: 34; radius: 17
                        color: Theme.field; border.color: Theme.lineSoft
                        Rectangle {   // kayan seçim
                            y: 3; height: parent.height - 6; radius: height / 2
                            x: modeSw.prod ? prodLbl.x + 4 : talkLbl.x + 4
                            width: modeSw.prod ? prodLbl.width : talkLbl.width
                            color: modeSw.prod ? "#9a3412" : "#1d4ed8"; opacity: 0.85
                            Behavior on x { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                            Behavior on width { NumberAnimation { duration: 180 } }
                            Behavior on color { ColorAnimation { duration: 180 } }
                        }
                        Row {
                            id: modeRow
                            x: 4; anchors.verticalCenter: parent.verticalCenter
                            Text { id: talkLbl; text: room.jailOk ? "💬 Tartışma" : "💬 Tartışma ⚠"; leftPadding: 10; rightPadding: 10
                                   color: modeSw.prod ? Theme.muted : "white"; font.pixelSize: Theme.fs(12) }
                            Text { id: prodLbl; text: "🛠 Üretim"; leftPadding: 10; rightPadding: 10
                                   color: modeSw.prod ? "white" : Theme.muted; font.pixelSize: Theme.fs(12) }
                        }
                        MouseArea {
                            id: modeMa
                            anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                            onClicked: { var s = cfg; s.production = !modeSw.prod; room.saveSettings(s)
                                         win.status = s.production ? "Üretim: ajanlar dosya yazabilir, komut çalıştırabilir"
                                                                   : (room.jailOk ? "Tartışma: proje kilitli, yalnızca taslak/ klasörüne yazılabilir"
                                                                                  : "Tartışmada dosya üretimi kullanılamıyor: bu makinede kutu (bubblewrap) kurulamadı") }
                        }
                        ToolTip.visible: modeMa.containsMouse; ToolTip.delay: 300
                        ToolTip.text: (room.jailOk ? "" : "⚠ Tartışmada dosya üretimi kullanılamıyor: bu makinede kutu (bubblewrap) kurulamadı.\n") + "Tartışma: sistem ve proje dosyaları yalnızca okunur; ajanlar terminali kullanabilir, resim, belge ve taslakları proje içindeki taslak/ klasörüne yazabilir.\nÜretim: yazabilir ve (izinli) komut çalıştırabilirler.\nMod değişince odaya kısa bir bilgi satırı düşer; yeni sohbet Tartışma ile açılır."
                    }

                    GhostButton {
                        visible: !topRow.tight
                        text: "📁  " + cfg.workDir.replace(/^.*\//, "")
                        enabled: !room.busy
                        implicitWidth: Math.min(topRow.tight ? 120 : 220, contentItem.implicitWidth + 24)
                        onClicked: win.pickFolder()
                        ToolTip.visible: hovered; ToolTip.text: "Proje klasörü: " + cfg.workDir + "\nDeğiştirmek için tıkla"
                    }

                    Text {
                        visible: !topRow.tight
                        text: "Tur ⓘ"; color: Theme.muted; font.pixelSize: Theme.fs(12)
                        MouseArea { id: turTip; anchors.fill: parent; hoverEnabled: true }
                        ToolTip.visible: turTip.containsMouse
                        ToolTip.text: "Sen yazdıktan sonra üç ajanın kaç kez sırayla konuşacağı.\nOto açıkken sayı yok: sen Durdur'a basana kadar konuşurlar.\nAjanlar bunu görmez."
                    }
                    SpinBox {
                        id: rounds
                        visible: !topRow.tight
                        enabled: !cfg.autoMode
                        opacity: enabled ? 1 : 0.35
                        from: 1; to: 20
                        value: cfg.autoRounds
                        implicitWidth: topRow.tight ? 88 : 104; implicitHeight: 32
                        ToolTip.visible: hovered && topRow.tight; ToolTip.delay: 400
                        ToolTip.text: "Tur: sen yazdıktan sonra ajanların kaç kez konuşacağı"
                        onValueModified: { var s = cfg; s.autoRounds = value; room.saveSettings(s) }
                        contentItem: Text {
                            text: rounds.value; color: Theme.text; font.pixelSize: Theme.fs(13)
                            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                        }
                        background: Rectangle { radius: 8; color: Theme.field; border.color: Theme.line }
                        up.indicator: Text { x: parent.width - width - 10; height: parent.height; text: "+"; color: Theme.textDim; font.pixelSize: Theme.fs(16); verticalAlignment: Text.AlignVCenter }
                        down.indicator: Text { x: 10; height: parent.height; text: "−"; color: Theme.textDim; font.pixelSize: Theme.fs(16); verticalAlignment: Text.AlignVCenter }
                    }
                    // Oto: müdahale olmadan akış
                    Rectangle {
                        id: autoChip
                        readonly property bool on: !!cfg.autoMode
                        implicitWidth: autoTxt.implicitWidth + 24; implicitHeight: 32; radius: 8
                        color: on ? Qt.rgba(Theme.user.r, Theme.user.g, Theme.user.b, 0.25) : Theme.field
                        border.color: on ? Theme.user : Theme.line
                        Behavior on color { ColorAnimation { duration: 150 } }
                        Text {
                            id: autoTxt
                            anchors.centerIn: parent
                            text: topRow.tight ? "∞" : "∞  Oto"
                            color: autoChip.on ? Theme.text : Theme.textDim
                            font.pixelSize: Theme.fs(12); font.weight: autoChip.on ? Font.DemiBold : Font.Normal
                        }
                        SequentialAnimation on opacity {
                            running: autoChip.on && room.busy; loops: Animation.Infinite
                            onRunningChanged: if (!running) autoChip.opacity = 1
                            NumberAnimation { to: 0.6; duration: 700 }
                            NumberAnimation { to: 1; duration: 700 }
                        }
                        MouseArea {
                            id: autoMa
                            anchors.fill: parent; hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: { var s = cfg; s.autoMode = !autoChip.on; room.saveSettings(s)
                                         win.status = s.autoMode ? "Oto açık — ajanlar sen durdurana kadar konuşur"
                                                                 : "Oto kapalı" }
                        }
                        ToolTip.visible: autoMa.containsMouse; ToolTip.delay: 300
                        Layout.preferredWidth: implicitWidth
                        ToolTip.text: "Açıkken ajanlar senin müdahalen olmadan konuşmaya devam eder.\nDurdurmak için ■ Durdur. Araya istediğin an yazabilirsin."
                    }
                    GhostButton { text: topRow.tight ? "▶" : "▶  Bir tur daha"; implicitWidth: topRow.tight ? 34 : implicitContentWidth + 24
                                  enabled: !room.busy && msgs.count > 0; onClicked: room.nextRound()
                                  ToolTip.visible: hovered && topRow.tight; ToolTip.text: "Bir tur daha" }
                    GhostButton { text: topRow.tight ? "■" : "■  Durdur"; implicitWidth: topRow.tight ? 34 : implicitContentWidth + 24
                                  enabled: room.busy; accent: "#ef4444"; onClicked: room.stop()
                                  ToolTip.visible: hovered && topRow.tight; ToolTip.text: "Hepsini durdur" }

                    // roller: ön tanımlı olarak kapalı; açıkken renkli
                    Rectangle {
                        id: rolesChip
                        readonly property bool on: room.roles.on
                        implicitWidth: rolesTxt.implicitWidth + 22; implicitHeight: 32; radius: 8
                        color: on ? Qt.rgba(Theme.user.r, Theme.user.g, Theme.user.b, 0.2) : rolesMa.containsMouse ? Theme.cardHi : Theme.field
                        border.color: on ? Theme.user : Theme.line
                        Behavior on color { ColorAnimation { duration: 150 } }
                        Text { id: rolesTxt; anchors.centerIn: parent; text: rolesChip.on ? "Roller açık" : "Roller"
                               color: rolesChip.on ? Theme.text : Theme.textDim; font.pixelSize: Theme.fs(12) }
                        MouseArea { id: rolesMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: rolesDlg.open() }
                        ToolTip.visible: rolesMa.containsMouse; ToolTip.delay: 400
                        ToolTip.text: rolesChip.on ? "Bu sohbette roller açık. Değiştirmek ya da kapatmak için tıkla."
                                                   : "Roller kapalı. Bu sohbet için hazır şablonla ya da elle rol belirle."
                    }
                    // durum paneli: aç / kapat
                    Rectangle {
                        id: panelBtn
                        implicitWidth: 34; implicitHeight: 34; radius: 9
                        color: panelMa.containsMouse ? Theme.cardHi : cfg.panelOpen !== false ? Theme.field : "transparent"
                        border.color: Theme.lineSoft
                        Rectangle { anchors.centerIn: parent; width: 16; height: 13; radius: 3; color: "transparent"
                                    border.color: cfg.panelOpen !== false ? Theme.text : Theme.muted; border.width: 1.4
                            Rectangle { x: parent.width - 6; y: 1; width: 1.4; height: parent.height - 2; color: parent.border.color }
                            Rectangle { visible: cfg.panelOpen !== false; x: parent.width - 4.6; y: 1.5; width: 3.2; height: parent.height - 3; radius: 1; color: Qt.rgba(parent.border.color.r, parent.border.color.g, parent.border.color.b, 0.5) } }
                        MouseArea { id: panelMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: win.togglePanel() }
                        ToolTip.visible: panelMa.containsMouse; ToolTip.delay: 400
                        ToolTip.text: cfg.panelOpen !== false ? "Durum panelini gizle" : "Durum panelini göster"
                    }

                    // tema: güneş / ay, dönerek değişir
                    Rectangle {
                        id: themeBtn
                        implicitWidth: 34; implicitHeight: 34; radius: 17
                        color: themeMa.containsMouse ? Theme.cardHi : "transparent"
                        border.color: Theme.lineSoft
                        Text {
                            id: themeIcon
                            anchors.centerIn: parent
                            text: Theme.dark ? "☾" : "☀"
                            color: Theme.dark ? "#c4b5fd" : "#f59e0b"; font.pixelSize: Theme.fs(16)
                            Behavior on rotation { NumberAnimation { duration: 500; easing.type: Easing.OutBack } }
                        }
                        MouseArea { id: themeMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                    onClicked: { themeIcon.rotation += 360; win.setTheme(Theme.dark ? "light" : "dark") } }
                        ToolTip.visible: themeMa.containsMouse; ToolTip.delay: 400
                        ToolTip.text: Theme.dark ? "Açık temaya geç" : "Koyu temaya geç"
                    }

                    // pencere düğmeleri
                    Row {
                        spacing: 2
                        Layout.leftMargin: 6
                        Repeater {
                            model: [{ t: "–", a: "min" }, { t: win.maxed ? "❐" : "□", a: "max" }, { t: "✕", a: "close" }]
                            Rectangle {
                                width: 34; height: 30; radius: 8
                                color: wma.containsMouse ? (modelData.a === "close" ? "#e5484d" : Theme.cardHi) : "transparent"
                                Behavior on color { ColorAnimation { duration: 120 } }
                                Text { anchors.centerIn: parent; text: modelData.t; font.pixelSize: Theme.fs(modelData.a === "max" ? 13 : 14)
                                       color: wma.containsMouse && modelData.a === "close" ? "white" : Theme.textDim }
                                MouseArea { id: wma; anchors.fill: parent; hoverEnabled: true
                                            onClicked: modelData.a === "min" ? win.showMinimized()
                                                     : modelData.a === "max" ? win.toggleMax() : win.close() }
                            }
                        }
                    }
                }
            }

            ListView {
                id: chat
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: msgs
                spacing: 8
                topMargin: 24; bottomMargin: 12
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                    contentItem: Rectangle { implicitWidth: 6; radius: 3; color: Theme.line; opacity: parent.active ? 1 : 0.5 }
                }
                delegate: MessageBubble {
                    width: chat.width
                    isUser: model.key === "user"
                    showHeader: index === 0 || msgs.get(index - 1).key !== model.key
                }

                // boş durum
                Column {
                    anchors.centerIn: parent
                    visible: msgs.count === 0
                    spacing: 14
                    Row {
                        anchors.horizontalCenter: parent.horizontalCenter
                        spacing: -10
                        Repeater {
                            model: [Theme.user].concat(cfg.agents.map(function(a){ return a.color }))
                            Rectangle {
                                width: 46; height: 46; radius: 23
                                color: modelData; border.color: Theme.bg; border.width: 3
                                SequentialAnimation on y {
                                    loops: Animation.Infinite
                                    PauseAnimation { duration: index * 180 }
                                    NumberAnimation { to: -6; duration: 700; easing.type: Easing.InOutSine }
                                    NumberAnimation { to: 0; duration: 700; easing.type: Easing.InOutSine }
                                }
                            }
                        }
                    }
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: "Bir konu aç"; color: Theme.text; font.pixelSize: Theme.fs(22); font.bold: true }
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: (win.enabledAgents.length === 1 ? win.enabledAgents[0].name + " odada." : "Hepsi odada.") + (room.roles.on ? " Bu sohbette roller açık." : " Kimseye rol verilmedi."); color: Theme.muted; font.pixelSize: Theme.fs(13) }
                }
            }

            // giriş: sütunla aynı genişlikte, havada duran bir kutu
            Item {
                Layout.fillWidth: true
                implicitHeight: composer.height + hint.implicitHeight + 26
                // gölge ayrı çizilir: kutuyu katmana almak, boyu değişene dek boş görünmesine yol açıyordu
                RectangularShadow {
                    x: composer.x; y: composer.y + 6
                    width: composer.width; height: composer.height
                    radius: composer.radius; blur: 22; spread: 0
                    color: Qt.rgba(0, 0, 0, Theme.shadow)
                }
                Rectangle {
                    id: composer
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 4
                    width: Math.min(parent.width - 40, Theme.column)
                    height: Math.min(200, input.implicitHeight + 26) + (attRow.visible ? attRow.height + 10 : 0)
                    Behavior on height { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }

                    // eklenecek dosyalar: resimse küçük önizleme, değilse adı; ✕ ile çıkar
                    Flow {
                        id: attRow
                        visible: win.attachments.length > 0
                        x: 12; y: 10; width: parent.width - 24
                        spacing: 6
                        Repeater {
                            model: win.attachments
                            Rectangle {
                                required property string modelData
                                required property int index
                                readonly property bool img: /\.(png|jpe?g|gif|webp|svg|bmp|avif)$/i.test(modelData)
                                width: (img ? 44 : 0) + nameTxt.implicitWidth + 44; height: 44; radius: 10
                                color: Theme.cardHi; border.color: Theme.lineSoft
                                Image {
                                    visible: parent.img
                                    x: 4; y: 4; width: 36; height: 36
                                    source: parent.img ? "file://" + parent.modelData : ""
                                    fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize: Qt.size(72, 72)
                                }
                                Text {
                                    id: nameTxt
                                    x: parent.img ? 48 : 12; anchors.verticalCenter: parent.verticalCenter
                                    text: (parent.img ? "" : "📄 ") + parent.modelData.replace(/^.*\//, "")
                                    width: Math.min(implicitWidth, 200); elide: Text.ElideMiddle
                                    color: Theme.textDim; font.pixelSize: Theme.fs(12)
                                }
                                Text {
                                    anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter
                                    text: "✕"; color: rmMa.containsMouse ? Theme.danger : Theme.muted; font.pixelSize: Theme.fs(12)
                                    MouseArea { id: rmMa; anchors.fill: parent; anchors.margins: -6; hoverEnabled: true
                                                cursorShape: Qt.PointingHandCursor; onClicked: win.removeAttachment(index) }
                                }
                                scale: 0.8; opacity: 0
                                Component.onCompleted: { scale = 1; opacity = 1 }
                                Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutBack } }
                                Behavior on opacity { NumberAnimation { duration: 150 } }
                            }
                        }
                    }
                    radius: 20
                    color: Theme.card
                    border.color: input.activeFocus ? Qt.rgba(Theme.user.r, Theme.user.g, Theme.user.b, 0.7) : Theme.line
                    Behavior on border.color { ColorAnimation { duration: 150 } }

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 8
                        anchors.leftMargin: 8
                        anchors.topMargin: attRow.visible ? attRow.height + 18 : 8
                        // ataç: dosya seç
                        Rectangle {
                            Layout.alignment: Qt.AlignBottom
                            width: 38; height: 38; radius: 19
                            color: clipMa.containsMouse ? Theme.cardHi : "transparent"
                            Text { anchors.centerIn: parent; text: "📎"; font.pixelSize: Theme.fs(17)
                                   rotation: clipMa.containsMouse ? -20 : 0
                                   Behavior on rotation { NumberAnimation { duration: 200; easing.type: Easing.OutBack } } }
                            MouseArea { id: clipMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                        onClicked: fileDlg.open() }
                            ToolTip.visible: clipMa.containsMouse; ToolTip.delay: 400
                            ToolTip.text: "Dosya ya da resim ekle (Ctrl+V ile yapıştır, pencereye sürükle-bırak)"
                        }
                        ScrollView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            TextArea {
                                id: input
                                placeholderText: "Odaya yaz…"
                                placeholderTextColor: Theme.muted
                                color: Theme.text
                                font.pixelSize: Theme.fs(14)
                                wrapMode: TextArea.Wrap
                                background: null
                                focus: true
                                Keys.onReturnPressed: function(e) {
                                    if (e.modifiers & Qt.ShiftModifier) { e.accepted = false; return }
                                    sendBtn.clicked()
                                }
                                // panoda resim ya da dosya varsa ek olarak al; yoksa normal yapıştır
                                Keys.onPressed: function(e) {
                                    if (e.matches(StandardKey.Paste)) {
                                        var f = room.pasteFromClipboard()
                                        if (f.length) { win.addAttachments(f); e.accepted = true }
                                    }
                                }
                            }
                        }
                        Rectangle {
                            id: sendBtn
                            signal clicked
                            readonly property bool ready: input.text.trim().length > 0 || win.attachments.length > 0
                            Layout.alignment: Qt.AlignBottom
                            width: 38; height: 38; radius: 19
                            scale: sendMa.pressed ? 0.88 : ready ? 1.0 : 0.94
                            Behavior on scale { NumberAnimation { duration: 160; easing.type: Easing.OutBack } }
                            gradient: ready ? sendGrad : null
                            color: Theme.cardHi
                            Gradient {
                                id: sendGrad
                                orientation: Gradient.Horizontal
                                GradientStop { position: 0; color: "#7c4dff" }
                                GradientStop { position: 1; color: "#9b6bff" }
                            }
                            Text { anchors.centerIn: parent; text: "↑"; color: sendBtn.ready ? "white" : Theme.muted
                                   font.pixelSize: Theme.fs(18); font.weight: Font.Bold }
                            MouseArea { id: sendMa; anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: sendBtn.clicked() }
                            onClicked: {
                                if (!ready) return
                                room.sendWith(input.text, win.attachments)
                                input.text = ""
                                win.attachments = []
                                var p = sendBtn.mapToItem(win.contentItem, sendBtn.width / 2, sendBtn.height / 2)
                                burst.fire(p.x, p.y)
                            }
                        }
                    }
                }
                Text {
                    id: hint
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.top: composer.bottom; anchors.topMargin: 8
                    text: "Enter gönderir · Shift+Enter yeni satır · 📎 ya da Ctrl+V ile resim ve dosya · " + win.enabledAgents.map(function(a) { return "@" + a.name.toLowerCase() }).join(", ") + " ile yalnızca birine söz ver"
                    width: Math.min(implicitWidth, parent.width - 40); elide: Text.ElideRight
                    color: Theme.muted; font.pixelSize: Theme.fs(11)
                }
            }
        }

        // ---------------- sağ: durum paneli ----------------
        StatusPanel {
            Layout.fillHeight: true
            Layout.preferredWidth: implicitWidth
            // dar pencerede yalnız şerit: sohbet sığsın
            open: cfg.panelOpen !== false && win.width >= 1100
            onToggle: if (win.width >= 1100) win.togglePanel(); else win.status = "Paneli açmak için pencereyi genişletin"
        }
    }

    RolesDialog { id: rolesDlg }

    Dialog {
        id: delDlg
        property string cid
        property string title_
        anchors.centerIn: parent
        modal: true
        width: 380
        padding: 20
        background: Rectangle { radius: 14; color: Theme.card; border.color: Theme.line }
        contentItem: Column {
            spacing: 16
            Text { text: "Sohbet silinsin mi?"; color: Theme.text; font.pixelSize: Theme.fs(16); font.bold: true }
            Text { width: 340; wrapMode: Text.WordWrap; color: Theme.textDim; font.pixelSize: Theme.fs(12)
                   text: "“" + delDlg.title_ + "” kalıcı olarak silinecek. Bu geri alınamaz." }
            Row {
                anchors.right: parent.right; spacing: 8
                GhostButton { text: "Vazgeç"; onClicked: delDlg.close() }
                GhostButton { text: "Sil"; accent: "#ef4444"; onClicked: { room.deleteChat(delDlg.cid); delDlg.close() } }
            }
        }
    }

    // tema geçişi: eski zemin rengi bir an üstte kalıp erir
    Rectangle {
        id: fade
        anchors.fill: parent; z: 900; opacity: 0; visible: opacity > 0
        NumberAnimation on opacity { id: fadeAnim; running: false; from: 0.85; to: 0; duration: 420; easing.type: Easing.OutCubic }
    }

    // gönderince küçük konfeti: üç ajanın ve senin renginde
    Item {
        id: burst
        anchors.fill: parent; z: 950
        function fire(x, y) {
            var cols = [Theme.user, "#4f8cff", "#d97757", "#10a37f"]
            for (var i = 0; i < 14; i++) {
                var a = Math.PI * (1.05 + Math.random() * 0.9)          // yukarı doğru bir yelpaze
                var d = 50 + Math.random() * 70
                dot.createObject(burst, { x: x, y: y, color: cols[i % 4], dx: Math.cos(a) * d, dy: Math.sin(a) * d,
                                          size: 4 + Math.random() * 5 })
            }
        }
        Component {
            id: dot
            Rectangle {
                id: d
                property real dx; property real dy; property real size: 6
                width: size; height: size; radius: size / 2
                ParallelAnimation {
                    running: true
                    NumberAnimation { target: d; property: "x"; to: d.x + d.dx; duration: 650; easing.type: Easing.OutCubic }
                    NumberAnimation { target: d; property: "y"; to: d.y + d.dy; duration: 650; easing.type: Easing.OutCubic }
                    NumberAnimation { target: d; property: "opacity"; from: 1; to: 0; duration: 650; easing.type: Easing.InQuad }
                    NumberAnimation { target: d; property: "scale"; from: 1.2; to: 0.4; duration: 650 }
                    onFinished: d.destroy()
                }
            }
        }
    }

    // çerçevesiz pencere: kenar ve köşelerden boyutlandırma
    Repeater {
        model: win.maxed ? [] : [
            { e: Qt.LeftEdge, x: 0, y: 6, w: 5, h: -12, c: Qt.SizeHorCursor },
            { e: Qt.RightEdge, x: -5, y: 6, w: 5, h: -12, c: Qt.SizeHorCursor },
            { e: Qt.TopEdge, x: 6, y: 0, w: -12, h: 4, c: Qt.SizeVerCursor },
            { e: Qt.BottomEdge, x: 6, y: -5, w: -12, h: 5, c: Qt.SizeVerCursor },
            { e: Qt.TopEdge | Qt.LeftEdge, x: 0, y: 0, w: 8, h: 8, c: Qt.SizeFDiagCursor },
            { e: Qt.TopEdge | Qt.RightEdge, x: -8, y: 0, w: 8, h: 8, c: Qt.SizeBDiagCursor },
            { e: Qt.BottomEdge | Qt.LeftEdge, x: 0, y: -8, w: 8, h: 8, c: Qt.SizeBDiagCursor },
            { e: Qt.BottomEdge | Qt.RightEdge, x: -8, y: -8, w: 8, h: 8, c: Qt.SizeFDiagCursor }]
        MouseArea {
            x: modelData.x < 0 ? win.width + modelData.x : modelData.x
            y: modelData.y < 0 ? win.height + modelData.y : modelData.y
            width: modelData.w < 0 ? win.width + modelData.w : modelData.w
            height: modelData.h < 0 ? win.height + modelData.h : modelData.h
            z: 1000
            cursorShape: modelData.c
            onPressed: win.startSystemResize(modelData.e)
        }
    }

    SettingsDrawer { id: settings; objectName: "settingsDrawer"; width: Math.min(560, win.width * 0.6); height: win.height }
}
