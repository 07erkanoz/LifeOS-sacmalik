import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import QtMultimedia

Item {
    id: root
    property bool isUser
    property bool showHeader: true
    readonly property color c: model.color
    readonly property bool isPending: model.pending
    readonly property string actsText: model.acts || ""
    readonly property bool isSystem: model.key === "system"

    // düz metindeki adresleri ve dosya yollarını tıklanabilir bağlantıya çevir
    function linkify(t) {
        if (!t) return t
        // kod olarak yazılmış SVG görsel aşağıda gösteriliyor: kodu katla
        t = t.replace(/```[\w-]*\n\s*(?:<\?xml[^>]*>\s*)?<svg\b[\s\S]*?```/gi, "*🖼 SVG görsel — aşağıda*")
        var base = (cfg.workDir || "").replace(/\/$/, "")
        function url(u) {
            if (/^https?:\/\//i.test(u)) return u
            if (/^(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?/i.test(u)) return "http://" + u
            if (u.charAt(0) === "~") return "file://" + u   // ev dizini: aşağıda çözülür
            if (u.charAt(0) === "/") return "file://" + u
            return "file://" + base + "/" + u.replace(/^\.\//, "")
        }
        var URL_RE = /(https?:\/\/[^\s<>)\]"'`]+|\b(?:localhost|127\.0\.0\.1|0\.0\.0\.0):\d+[^\s<>)\]"'`]*|(?:^|(?=\/))\/(?:[\w.\-~%]+\/)+[\w.\-~%]*)/g
        function plain(seg) {
            return seg.replace(URL_RE, function(m, _g, off, all) {
                var prev = all.charAt(off - 1), prev2 = all.substr(Math.max(0, off - 2), 2)
                if (prev2 === "](" || prev === "<" || prev === "(" && all.charAt(off - 2) === "]") return m
                if (m.charAt(0) === "/" && /[\w:]/.test(prev)) return m        // a/b gibi kelime içi
                var clean = m.replace(/[.,;:!?]+$/, ""), tail = m.substr(clean.length)
                return "[" + clean + "](" + url(clean) + ")" + tail
            })
        }
        // kod bloklarına dokunma; satır içi `kod` bir adres ya da yolsa bağlantı yap
        var parts = t.split(/(```[\s\S]*?```)/g)
        for (var i = 0; i < parts.length; i++) {
            if (parts[i].indexOf("```") === 0) continue
            var bits = parts[i].split(/(`[^`\n]+`)/g)
            for (var j = 0; j < bits.length; j++) {
                var b = bits[j]
                if (b.charAt(0) === "`" && b.length > 2) {
                    var inner = b.slice(1, -1)
                    if (/^(https?:\/\/|localhost:|127\.0\.0\.1:|\/|~\/|\.\/)\S+$/.test(inner) || /^[\w\-.]+\/[\w\-.\/]+\.\w{1,5}$/.test(inner)
                            || /^[\w\-]+\.(png|jpe?g|gif|webp|svg|mp4|webm|mov|html?|pdf|md|js|css|py|json|txt)$/i.test(inner))
                        bits[j] = "[`" + inner + "`](" + url(inner) + ")"
                } else bits[j] = plain(b)
            }
            parts[i] = bits.join("")
        }
        return parts.join("")
    }
    // kullanıcı balonu: eklerin yolları ajanlar içindir, ekranda kart olarak görünürler
    readonly property string shownBody: isUser ? model.body.replace(/\n*\*\*Ekler:\*\*\n(?:- `[^`\n]+`\n?)+$/, "") : model.body
    function html(md) {
        var h = room.renderMd(root.linkify(md), Theme.dark, Theme.scale)
        if (!isUser) return h
        // mor zeminde okunur: bağlantılar beyaz, kod şeffaf beyaz zeminde
        return h.replace(/color:#(?:8fb3ff|3b6fe0);/g, "color:#ffffff;")
                .replace(/color:#(?:f5c97a|a64f0b);/g, "color:#ffffff;")
                .replace(/background-color:#(?:232836|f3ede4);/g, "background-color:rgba(255,255,255,0.18);")
    }
    function openLink(l) {
        if (/^file:\/\//.test(l)) {
            var f = decodeURIComponent(l.replace(/^file:\/\//, ""))
            if (f.charAt(0) === "~") f = room.homeDir + f.slice(1)
            if (/\.(png|jpe?g|gif|webp|svg|bmp|avif|mp4|webm|mov|mkv|ogv)$/i.test(f)) win.showImage(f)
            else Qt.openUrlExternally("file://" + f)
        } else if (l.charAt(0) === "/") openLink("file://" + l)
        else Qt.openUrlExternally(l)
    }
    // mesajlar ekran ne kadar geniş olursa olsun ortada, okunur genişlikte bir sütunda durur
    readonly property real side: Math.max(20, (width - Theme.column) / 2)
    readonly property real maxW: Math.min(isUser ? 620 : 720, (width - 2 * side - 48) * (isUser ? 0.8 : 0.92))
    implicitHeight: isSystem ? sysPill.height + 14 : row.implicitHeight + (showHeader ? 12 : 0)

    // oda bilgisi (mod değişikliği, anlaşma, dosya değişikliği): ortada küçük bir hap
    Rectangle {
        id: sysPill
        visible: root.isSystem
        anchors.centerIn: parent
        width: Math.min(sysTxt.implicitWidth + 28, root.width - 2 * root.side)
        height: sysTxt.implicitHeight + 12
        radius: Math.min(height / 2, 14)
        color: Theme.panel
        border.color: Theme.lineSoft
        Text {
            id: sysTxt
            anchors.centerIn: parent
            width: Math.min(implicitWidth, root.width - 2 * root.side - 28)
            text: root.isSystem ? model.body + "   " + model.time : ""
            textFormat: Text.MarkdownText
            color: Theme.textDim; font.pixelSize: Theme.fs(12)
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
        }
    }

    // giriş animasyonu
    opacity: 0
    transform: [
        Translate { id: tr; y: 10; x: root.isSystem ? 0 : (root.isUser ? 18 : -18) },
        Scale { id: sc; origin.x: root.isUser ? root.width : 0; origin.y: root.height; xScale: 0.98; yScale: 0.98 }
    ]
    Component.onCompleted: appear.start()
    ParallelAnimation {
        id: appear
        NumberAnimation { target: root; property: "opacity"; to: 1; duration: 260; easing.type: Easing.OutCubic }
        NumberAnimation { target: tr; property: "y"; to: 0; duration: 340; easing.type: Easing.OutBack; easing.overshoot: 1.2 }
        NumberAnimation { target: tr; property: "x"; to: 0; duration: 340; easing.type: Easing.OutCubic }
        NumberAnimation { target: sc; properties: "xScale,yScale"; to: 1; duration: 300; easing.type: Easing.OutCubic }
    }

    RowLayout {
        id: row
        visible: !root.isSystem
        anchors.left: parent.left; anchors.right: parent.right
        anchors.leftMargin: root.side; anchors.rightMargin: root.side
        anchors.bottom: parent.bottom
        layoutDirection: isUser ? Qt.RightToLeft : Qt.LeftToRight
        spacing: 12

        // avatar
        Item {
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: 32; Layout.preferredHeight: 32
            Rectangle {
                visible: showHeader
                anchors.fill: parent; radius: 16
                gradient: Gradient {
                    GradientStop { position: 0; color: Qt.lighter(root.c, 1.25) }
                    GradientStop { position: 1; color: Qt.darker(root.c, 1.15) }
                }
                Text { anchors.centerIn: parent; text: model.name.charAt(0); color: "white"; font.weight: Font.Bold; font.pixelSize: Theme.fs(13) }
            }
        }

        ColumnLayout {
            spacing: 5
            Layout.maximumWidth: root.maxW
            Layout.alignment: isUser ? Qt.AlignRight : Qt.AlignLeft

            RowLayout {
                visible: showHeader
                spacing: 8
                Layout.alignment: isUser ? Qt.AlignRight : Qt.AlignLeft
                Text { text: model.name; color: isUser ? Theme.textDim : root.c; font.pixelSize: Theme.fs(13); font.weight: Font.DemiBold }
                Text { text: model.time; color: Theme.muted; font.pixelSize: Theme.fs(11) }
                Text {
                    visible: !model.pending && model.secs > 0
                    text: model.secs.toFixed(1) + " sn"; color: Theme.muted; font.pixelSize: Theme.fs(11)
                }
            }

            Rectangle {
                visible: model.silent
                implicitWidth: silentTxt.implicitWidth + 20; implicitHeight: 24; radius: 12
                color: "transparent"; border.color: Theme.lineSoft
                Text { id: silentTxt; anchors.centerIn: parent; text: "sessiz kaldı"; color: Theme.muted; font.pixelSize: Theme.fs(11) }
            }

            // canlı etkinlik: ajanın o an yaptıkları (dosya, komut)
            Rectangle {
                id: actBox
                readonly property var lines: root.actsText ? root.actsText.split("\n") : []
                property bool open: false
                visible: lines.length > 0
                Layout.alignment: isUser ? Qt.AlignRight : Qt.AlignLeft
                Layout.maximumWidth: root.maxW
                implicitWidth: actCol.implicitWidth + 22
                implicitHeight: actCol.implicitHeight + 14
                radius: 10
                color: Theme.panel
                border.color: root.isPending ? Qt.rgba(root.c.r, root.c.g, root.c.b, 0.35) : Theme.lineSoft
                Column {
                    id: actCol
                    x: 11; y: 7
                    spacing: 3
                    Text {
                        visible: !root.isPending
                        text: (actBox.open ? "▾  " : "▸  ") + actBox.lines.length + " işlem"
                        color: Theme.textDim; font.pixelSize: Theme.fs(11); font.weight: Font.Medium
                        MouseArea { anchors.fill: parent; anchors.margins: -4; cursorShape: Qt.PointingHandCursor; onClicked: actBox.open = !actBox.open }
                    }
                    Repeater {
                        model: root.isPending ? actBox.lines.slice(-4) : (actBox.open ? actBox.lines : [])
                        Text {
                            text: modelData
                            width: Math.min(implicitWidth, root.maxW - 22)
                            elide: Text.ElideRight
                            color: index === actBox.lines.slice(-4).length - 1 && root.isPending ? Theme.textDim : Theme.muted
                            font.pixelSize: Theme.fs(11); font.family: Theme.mono
                        }
                    }
                }
            }

            Rectangle {
                id: bubble
                readonly property bool typing: model.pending && !model.body.length
                visible: !model.silent && (root.shownBody.length > 0 || model.pending)
                Layout.alignment: isUser ? Qt.AlignRight : Qt.AlignLeft
                implicitWidth: typing ? 68 : Math.min(body.implicitWidth + 32, root.maxW)
                implicitHeight: typing ? 38 : body.implicitHeight + 24
                radius: 18
                topLeftRadius: isUser || !showHeader ? 18 : 6
                topRightRadius: isUser && showHeader ? 6 : 18
                gradient: isUser ? userGrad : null
                color: !model.ok ? Qt.rgba(0.97, 0.44, 0.44, 0.08) : Theme.card
                Behavior on color { ColorAnimation { duration: 250 } }
                border.width: isUser ? 0 : 1
                border.color: !model.ok ? Qt.rgba(0.97, 0.44, 0.44, 0.35)
                            : model.pending ? Qt.rgba(root.c.r, root.c.g, root.c.b, 0.25 + 0.4 * glow)
                            : bh.hovered ? Qt.rgba(root.c.r, root.c.g, root.c.b, 0.35) : Theme.lineSoft
                property real glow: 0
                SequentialAnimation on glow {
                    running: model.pending; loops: Animation.Infinite
                    NumberAnimation { to: 1; duration: 900; easing.type: Easing.InOutSine }
                    NumberAnimation { to: 0; duration: 900; easing.type: Easing.InOutSine }
                }
                HoverHandler { id: bh }
                Behavior on implicitHeight { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                Behavior on implicitWidth { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                Gradient {
                    id: userGrad
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: "#7c4dff" }
                    GradientStop { position: 1; color: "#9b6bff" }
                }

                // yazıyor animasyonu
                Row {
                    anchors.centerIn: parent
                    visible: bubble.typing
                    spacing: 6
                    Repeater {
                        model: 3
                        Rectangle {
                            width: 7; height: 7; radius: 3.5; color: root.c
                            SequentialAnimation on y {
                                loops: Animation.Infinite
                                PauseAnimation { duration: index * 140 }
                                NumberAnimation { to: -5; duration: 260; easing.type: Easing.OutQuad }
                                NumberAnimation { to: 0; duration: 260; easing.type: Easing.InQuad }
                                PauseAnimation { duration: 420 + (2 - index) * 140 }
                            }
                            SequentialAnimation on opacity {
                                loops: Animation.Infinite
                                PauseAnimation { duration: index * 140 }
                                NumberAnimation { to: 1; duration: 260 }
                                NumberAnimation { to: 0.45; duration: 260 }
                                PauseAnimation { duration: 420 + (2 - index) * 140 }
                            }
                        }
                    }
                }

                TextEdit {
                    id: body
                    visible: root.shownBody.length > 0
                    x: 16; y: 12
                    width: Math.min(implicitWidth, root.maxW - 32)
                    textFormat: TextEdit.RichText      // metinden önce: yoksa ilk ayrıştırma biçimsiz yapılıyor
                    text: root.shownBody.length ? root.html(root.shownBody) : ""
                    wrapMode: TextEdit.Wrap
                    readOnly: true
                    selectByMouse: true
                    color: isUser ? "white" : Theme.text
                    selectionColor: isUser ? Qt.rgba(1, 1, 1, 0.3) : Qt.rgba(root.c.r, root.c.g, root.c.b, 0.45)
                    font.pixelSize: Theme.fs(14)
                    onLinkActivated: function(l) { root.openLink(l) }
                    HoverHandler { cursorShape: body.hoveredLink ? Qt.PointingHandCursor : Qt.IBeamCursor }
                }
            }

            // ajanın ürettiği dosyalar: resimler önizlenir, diğerleri tıklayınca açılır
            Flow {
                id: mediaFlow
                readonly property var files: model.media ? model.media.split("\n").filter(function(f) { return f.length }) : []
                visible: files.length > 0
                Layout.alignment: isUser ? Qt.AlignRight : Qt.AlignLeft
                Layout.maximumWidth: root.maxW
                Layout.preferredWidth: root.maxW
                layoutDirection: isUser ? Qt.RightToLeft : Qt.LeftToRight
                spacing: 8
                Repeater {
                    model: mediaFlow.files
                    Loader {
                        required property string modelData
                        readonly property bool isImg: /\.(png|jpe?g|gif|webp|svg|bmp|avif)$/i.test(modelData)
                        readonly property bool isVid: /\.(mp4|webm|mov|mkv|ogv)$/i.test(modelData)
                        sourceComponent: isImg ? imgCard : isVid ? vidCard : fileChip
                        property string path: modelData
                    }
                }
            }
        }
        Item { Layout.fillWidth: true }
    }

    Component {
        id: imgCard
        Rectangle {
            readonly property string path: parent ? parent.path : ""
            width: Math.max(120, Math.min(img.status === Image.Ready ? img.paintedWidth : 280, 340))
            height: img.status === Image.Ready ? Math.min(img.paintedHeight, 240) + 26 : 160
            radius: 12; color: Theme.card; clip: true
            border.color: ma.containsMouse ? root.c : Theme.lineSoft
            Image {
                id: img
                x: 0; y: 0
                width: Math.min(340, implicitWidth > 0 ? implicitWidth : 340)
                height: Math.min(240, implicitHeight > 0 ? implicitHeight : 240)
                source: "file://" + parent.path
                fillMode: Image.PreserveAspectFit
                horizontalAlignment: Image.AlignLeft; verticalAlignment: Image.AlignTop
                asynchronous: true; cache: false; smooth: true; mipmap: true
                sourceSize.width: 680
            }
            Text {
                visible: img.status !== Image.Ready
                anchors.centerIn: parent; color: Theme.muted; font.pixelSize: Theme.fs(12)
                text: img.status === Image.Error ? "resim açılamadı" : "yükleniyor…"
            }
            Text {
                anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
                anchors.margins: 6; elide: Text.ElideMiddle
                text: "🖼 " + parent.path.replace(/^.*\//, ""); color: Theme.textDim; font.pixelSize: Theme.fs(11)
            }
            MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: win.showImage(parent.path) }
        }
    }
    Component {
        id: vidCard
        Rectangle {
            readonly property string path: parent ? parent.path : ""
            width: 340; height: 191 + 26; radius: 12; color: "black"; clip: true
            border.color: vma.containsMouse ? root.c : Theme.lineSoft
            Video {
                id: vid
                width: parent.width; height: 191
                source: "file://" + parent.path
                fillMode: VideoOutput.PreserveAspectFit
                muted: true; loops: MediaPlayer.Infinite
                Component.onCompleted: play()       // sessiz döngü önizleme
            }
            Text {
                anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
                anchors.margins: 6; elide: Text.ElideMiddle
                text: "🎬 " + parent.path.replace(/^.*\//, ""); color: Theme.textDim; font.pixelSize: Theme.fs(11)
            }
            MouseArea { id: vma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: win.showImage(parent.path) }
        }
    }
    Component {
        id: fileChip
        Rectangle {
            readonly property string path: parent ? parent.path : ""
            width: chipTxt.implicitWidth + 24; height: 34; radius: 10
            color: ma2.containsMouse ? Qt.rgba(root.c.r, root.c.g, root.c.b, 0.15) : Theme.card
            border.color: ma2.containsMouse ? root.c : Theme.line
            Text {
                id: chipTxt; anchors.centerIn: parent; color: Theme.text; font.pixelSize: Theme.fs(12)
                text: (/\.pdf$/i.test(parent.path) ? "📕 " : /\.(mp3|wav|ogg)$/i.test(parent.path) ? "🔊 " : /\.html?$/i.test(parent.path) ? "🌐 " : "📄 ") + parent.path.replace(/^.*\//, "") + "  ↗"
            }
            MouseArea { id: ma2; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: Qt.openUrlExternally("file://" + parent.path) }
            ToolTip.visible: ma2.containsMouse; ToolTip.text: parent.path + "\n(tarayıcıda / varsayılan uygulamada açılır)"
        }
    }
}
