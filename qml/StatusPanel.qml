import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Shapes
import QtMultimedia

// Sağdaki durum paneli: odadaki ajanlar (ne yaptıkları, ne kadar sürdüğü, durdurma) ve bu sohbette üretilen
// dosyalar (görseller, kod, belgeler). Ajan listesi ayarlardaki ajanlardan gelir: ajan eklenince panel de değişir.
// Kapalıyken ince bir şerit kalır: ajanların durum halkaları ve dosya sayısı.
Rectangle {
    id: pn
    property bool open: true
    signal toggle
    readonly property var agents: (win.cfg.agents || []).filter(function(a) { return a.enabled })
    readonly property var st: room.agentStatus
    readonly property var files: room.producedFiles
    readonly property int runningCount: agents.filter(function(a) { return (st[a.key] || {}).state === "running" }).length
    property int tab: 0                     // 0 görseller · 1 ses · 2 kod · 3 belgeler
    property real now: Date.now() / 1000
    Timer { interval: 1000; repeat: true; running: pn.runningCount > 0; onTriggered: pn.now = Date.now() / 1000 }

    function elapsed(t0) {
        if (!t0) return ""
        var s = Math.max(0, Math.floor(pn.now - t0)), m = Math.floor(s / 60)
        return m >= 60 ? Math.floor(m / 60) + " sa " + (m % 60) + " dk" : m + ":" + ("0" + (s % 60)).slice(-2)
    }
    function mins(s) { return s >= 60 ? Math.floor(s / 60) + " dk" : s + " sn" }
    function ofKind(k) { return pn.files.filter(function(f) { return f.kind === k }) }
    readonly property var images: ofKind("image")
    readonly property var audios: ofKind("audio")
    readonly property var codes: ofKind("code")
    readonly property var docs: ofKind("doc")

    implicitWidth: open ? 324 : 58
    Behavior on implicitWidth { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
    color: Theme.panel
    clip: true
    Rectangle { width: 1; height: parent.height; color: Theme.line }

    // ---------------- dar şerit (kapalı) ----------------
    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        y: 16; spacing: 14
        opacity: pn.open ? 0 : 1; visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 160 } }
        IconBtn { anchors.horizontalCenter: parent.horizontalCenter; glyph: "‹"; tip: "Durum panelini aç"; onClicked: pn.toggle() }
        Repeater {
            model: pn.agents
            Avatar {
                anchors.horizontalCenter: parent.horizontalCenter
                size: 30; name: modelData.name; tint: modelData.color
                state_: (pn.st[modelData.key] || {}).state || "idle"
                stuck: !!(pn.st[modelData.key] || {}).stuck
                muted: !!(pn.st[modelData.key] || {}).muted
                ToolTip.visible: am.containsMouse; ToolTip.delay: 300
                ToolTip.text: modelData.name + ((pn.st[modelData.key] || {}).state === "running" ? " · çalışıyor" : "")
                MouseArea { id: am; anchors.fill: parent; hoverEnabled: true; onClicked: pn.toggle() }
            }
        }
        Rectangle {
            visible: pn.files.length > 0
            anchors.horizontalCenter: parent.horizontalCenter
            width: cnt.implicitWidth + 12; height: 20; radius: 7; color: Theme.cardHi
            Text { id: cnt; anchors.centerIn: parent; text: pn.files.length; color: Theme.textDim; font.pixelSize: Theme.fs(11) }
            ToolTip.visible: cm.containsMouse; ToolTip.text: pn.files.length + " üretilen dosya"
            MouseArea { id: cm; anchors.fill: parent; hoverEnabled: true; onClicked: pn.toggle() }
        }
    }

    // ---------------- panel (açık) ----------------
    ColumnLayout {
        width: 324; height: parent.height
        spacing: 0
        opacity: pn.open ? 1 : 0; visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 180 } }

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 20; Layout.rightMargin: 12; Layout.topMargin: 16; Layout.bottomMargin: 6
            spacing: 4
            ColumnLayout {
                spacing: 1
                Text { text: "Oda"; color: Theme.text; font.pixelSize: Theme.fs(14); font.weight: Font.DemiBold }
                Text {
                    color: Theme.muted; font.pixelSize: Theme.fs(11)
                    text: pn.agents.length + " ajan · " + (pn.runningCount ? pn.runningCount + " çalışıyor" : "hepsi boşta")
                }
            }
            Item { Layout.fillWidth: true }
            IconBtn {
                visible: pn.runningCount > 0
                tip: "Hepsini durdur"; danger: true; onClicked: room.stop()
                Rectangle { anchors.centerIn: parent; width: 16; height: 16; radius: 8; color: "transparent"; border.color: parent.fg; border.width: 1.4
                    Rectangle { anchors.centerIn: parent; width: 6; height: 6; radius: 1.5; color: parent.border.color } }
            }
            IconBtn { glyph: "›"; tip: "Paneli gizle"; onClicked: pn.toggle() }
        }

        // ajanlar
        ListView {
            id: agentList
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(contentHeight, pn.height * 0.5)
            Layout.leftMargin: 10; Layout.rightMargin: 10
            interactive: contentHeight > height
            clip: true
            spacing: 2
            model: pn.agents
            delegate: AgentRow { width: agentList.width; a: modelData; s: pn.st[modelData.key] || {} }
        }

        Rectangle { Layout.fillWidth: true; Layout.leftMargin: 20; Layout.rightMargin: 20; Layout.topMargin: 10; height: 1; color: Theme.lineSoft }

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 20; Layout.rightMargin: 18; Layout.topMargin: 12; Layout.bottomMargin: 10
            Text { text: "Üretilenler"; color: Theme.textDim; font.pixelSize: Theme.fs(12); font.weight: Font.DemiBold }
            Item { Layout.fillWidth: true }
            Text { visible: pn.files.length > 0; text: pn.files.length + " dosya"; color: Theme.muted; font.pixelSize: Theme.fs(11) }
        }

        // kayan seçici
        Rectangle {
            id: seg
            Layout.fillWidth: true; Layout.leftMargin: 16; Layout.rightMargin: 16
            implicitHeight: 32; radius: 10
            color: Theme.dark ? "#0d0f15" : "#eceef4"
            border.color: Theme.lineSoft
            readonly property real cw: (width - 6) / 4
            Rectangle {
                x: 3 + pn.tab * seg.cw; y: 3; width: seg.cw; height: parent.height - 6; radius: 8
                color: Theme.dark ? "#232733" : "#ffffff"
                border.color: Theme.dark ? Qt.rgba(1, 1, 1, 0.05) : Theme.line
                Behavior on x { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
            }
            Row {
                x: 3; y: 3
                Repeater {
                    model: [["Görsel", pn.images.length], ["Ses", pn.audios.length], ["Kod", pn.codes.length], ["Belge", pn.docs.length]]
                    Item {
                        width: seg.cw; height: seg.height - 6
                        Row {
                            anchors.centerIn: parent; spacing: 5
                            Text { text: modelData[0]; color: pn.tab === index ? Theme.text : Theme.muted; font.pixelSize: Theme.fs(12)
                                   Behavior on color { ColorAnimation { duration: 150 } } }
                            Text { visible: modelData[1] > 0; text: modelData[1]; color: Theme.muted; font.pixelSize: Theme.fs(10.5)
                                   anchors.verticalCenter: parent.verticalCenter }
                        }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: pn.tab = index }
                    }
                }
            }
        }

        Item {
            Layout.fillWidth: true; Layout.fillHeight: true
            Layout.topMargin: 10

            // görseller: küçük önizlemeler, tıklayınca büyük
            GridView {
                id: grid
                anchors.fill: parent; anchors.leftMargin: 16; anchors.rightMargin: 12
                visible: pn.tab === 0
                clip: true
                cellWidth: Math.floor(width / 3); cellHeight: cellWidth
                model: pn.images
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: Item {
                    width: grid.cellWidth; height: grid.cellHeight
                    readonly property bool vid: /\.(mp4|webm|mov|mkv|ogv)$/i.test(modelData.path)
                    Rectangle {
                        id: th
                        anchors.fill: parent; anchors.margins: 3; radius: 10
                        color: Theme.cardHi; clip: true
                        layer.enabled: true
                        Image {
                            anchors.fill: parent
                            visible: !parent.parent.vid || !!modelData.thumb
                            source: parent.parent.vid ? (modelData.thumb ? "file://" + modelData.thumb : "") : "file://" + modelData.path
                            sourceSize: Qt.size(220, 220)
                            fillMode: Image.PreserveAspectCrop; asynchronous: true; smooth: true; cache: false
                            scale: tm.containsMouse ? 1.06 : 1
                            Behavior on scale { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
                        }
                        Rectangle {   // video: kare üstünde oynat işareti
                            visible: parent.parent.vid
                            anchors.centerIn: parent; width: 30; height: 30; radius: 15
                            color: Qt.rgba(0, 0, 0, 0.55); border.color: Qt.rgba(1, 1, 1, 0.35)
                            Text { anchors.centerIn: parent; anchors.horizontalCenterOffset: 1; text: "▶"; color: "white"; font.pixelSize: Theme.fs(12) }
                        }
                        Rectangle {   // altta ad: üstüne gelince
                            anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
                            height: 30; opacity: tm.containsMouse ? 1 : 0
                            Behavior on opacity { NumberAnimation { duration: 150 } }
                            gradient: Gradient { GradientStop { position: 0; color: "transparent" } GradientStop { position: 1; color: Qt.rgba(0, 0, 0, 0.78) } }
                            Text { x: 7; width: parent.width - 14; anchors.bottom: parent.bottom; anchors.bottomMargin: 5
                                   text: modelData.name; color: "white"; font.pixelSize: Theme.fs(10); elide: Text.ElideMiddle }
                        }
                        Rectangle {
                            visible: modelData.change === "yeni" && index === 0
                            x: 6; y: 6; radius: 6; width: yt.implicitWidth + 10; height: 17; color: Qt.rgba(0, 0, 0, 0.6)
                            Text { id: yt; anchors.centerIn: parent; text: "yeni"; color: "white"; font.pixelSize: Theme.fs(9.5); font.weight: Font.DemiBold }
                        }
                    }
                    Rectangle { x: parent.width - 15; y: 9; width: 8; height: 8; radius: 4; color: modelData.color
                                border.color: Qt.rgba(0, 0, 0, 0.35); border.width: 1.5 }
                    MouseArea {
                        id: tm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: win.showImage(modelData.path)
                    }
                    ToolTip.visible: tm.containsMouse; ToolTip.delay: 600
                    ToolTip.text: modelData.name + "\n" + (modelData.who || "?") + " · " + modelData.change + "\n" + modelData.dir
                }
                Empty { visible: grid.count === 0; text: "Henüz görsel yok" }
            }

            // kod ve belgeler: satırlar
            ListView {
                id: rows
                anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 10
                visible: pn.tab >= 2
                clip: true; spacing: 1
                model: pn.tab === 2 ? pn.codes : pn.docs
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: Rectangle {
                    width: rows.width; height: 48; radius: 10
                    color: rm.containsMouse ? Theme.cardHi : "transparent"
                    opacity: modelData.inside ? 1 : 0.62
                    Behavior on color { ColorAnimation { duration: 120 } }
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 8; anchors.rightMargin: 10
                        spacing: 10
                        Rectangle {
                            readonly property var c: badgeColor(modelData.ext)
                            width: 32; height: 32; radius: 8
                            color: Qt.rgba(c.r, c.g, c.b, Theme.dark ? 0.16 : 0.12)
                            Text { anchors.centerIn: parent; text: badge(modelData.ext); color: parent.c
                                   font.pixelSize: Theme.fs(badge(modelData.ext).length > 3 ? 8.5 : 9.5); font.weight: Font.Bold; font.letterSpacing: 0.3 }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 1
                            Text { Layout.fillWidth: true; text: modelData.name; color: Theme.text; font.pixelSize: Theme.fs(12.5)
                                   font.weight: Font.Medium; elide: Text.ElideMiddle }
                            Text { Layout.fillWidth: true; color: Theme.muted; font.pixelSize: Theme.fs(10.5); elide: Text.ElideMiddle
                                   text: (modelData.dir || "proje kökü") + (modelData.inside ? "" : " · proje dışında") }
                        }
                        ColumnLayout {
                            spacing: 3
                            Text { Layout.alignment: Qt.AlignRight; text: modelData.change
                                   color: modelData.change === "yeni" ? Theme.ok : Theme.muted; font.pixelSize: Theme.fs(10) }
                            Rectangle { Layout.alignment: Qt.AlignRight; width: 7; height: 7; radius: 3.5; color: modelData.color }
                        }
                    }
                    MouseArea { id: rm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                onClicked: Qt.openUrlExternally("file://" + modelData.path) }
                    ToolTip.visible: rm.containsMouse; ToolTip.delay: 600
                    ToolTip.text: modelData.path + "\n" + (modelData.who || "?") + " · " + modelData.change + "\nTıkla: aç"
                }
                Empty { visible: rows.count === 0; text: pn.tab === 2 ? "Henüz kod yok" : "Henüz belge yok" }
            }

            // ses: panelin içinde dinlenir; çift tıklayınca dışarıda açılır
            MediaPlayer {
                id: player
                property string current: ""
                audioOutput: AudioOutput { }
                onPlaybackStateChanged: if (playbackState === MediaPlayer.StoppedState) current = ""
            }
            ListView {
                id: sounds
                anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 10
                visible: pn.tab === 1
                clip: true; spacing: 1
                model: pn.audios
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: Rectangle {
                    readonly property bool playing: player.current === modelData.path && player.playbackState === MediaPlayer.PlayingState
                    width: sounds.width; height: 52; radius: 10
                    color: playing ? Qt.rgba(Qt.color(modelData.color).r, Qt.color(modelData.color).g, Qt.color(modelData.color).b, 0.12)
                         : sm.containsMouse ? Theme.cardHi : "transparent"
                    Behavior on color { ColorAnimation { duration: 140 } }
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 8; anchors.rightMargin: 10
                        spacing: 10
                        Rectangle {
                            width: 32; height: 32; radius: 16
                            color: parent.parent.playing ? modelData.color : Qt.rgba(Qt.color(modelData.color).r, Qt.color(modelData.color).g, Qt.color(modelData.color).b, 0.18)
                            Text { anchors.centerIn: parent; anchors.horizontalCenterOffset: parent.parent.parent.playing ? 0 : 1
                                   text: parent.parent.parent.playing ? "❚❚" : "▶"; color: parent.parent.parent.playing ? "white" : modelData.color
                                   font.pixelSize: Theme.fs(parent.parent.parent.playing ? 9 : 11); font.bold: true }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 2
                            Text { Layout.fillWidth: true; text: modelData.name; color: Theme.text; font.pixelSize: Theme.fs(12.5)
                                   font.weight: Font.Medium; elide: Text.ElideMiddle }
                            // çalarken ilerleme, değilse klasör ve boyut
                            Item {
                                Layout.fillWidth: true; implicitHeight: 13
                                Rectangle {
                                    visible: parent.parent.parent.parent.playing
                                    anchors.verticalCenter: parent.verticalCenter; width: parent.width; height: 3; radius: 1.5; color: Theme.line
                                    Rectangle { height: parent.height; radius: 1.5; color: modelData.color
                                                width: player.duration > 0 ? parent.width * player.position / player.duration : 0 }
                                }
                                Text {
                                    visible: !parent.parent.parent.parent.playing
                                    width: parent.width; elide: Text.ElideMiddle; color: Theme.muted; font.pixelSize: Theme.fs(10.5)
                                    text: (modelData.dir || "proje kökü") + " · " + Math.max(1, Math.round(modelData.size / 1024)) + " KB"
                                }
                            }
                        }
                        Rectangle { width: 7; height: 7; radius: 3.5; color: modelData.color }
                    }
                    MouseArea {
                        id: sm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (parent.playing) { player.pause(); return }
                            if (player.current !== modelData.path) { player.source = "file://" + modelData.path; player.current = modelData.path }
                            player.play()
                        }
                        onDoubleClicked: Qt.openUrlExternally("file://" + modelData.path)
                    }
                    ToolTip.visible: sm.containsMouse; ToolTip.delay: 600
                    ToolTip.text: modelData.path + "\n" + (modelData.who || "?") + " · " + modelData.change + "\nTıkla: dinle · çift tıkla: dışarıda aç"
                }
                Empty { visible: sounds.count === 0; text: "Henüz ses yok" }
            }
        }
    }

    function badge(e) {
        var m = { py: "PY", js: "JS", mjs: "JS", ts: "TS", tsx: "TSX", jsx: "JSX", dart: "DART", qml: "QML", rs: "RS",
                  go: "GO", html: "HTML", htm: "HTML", css: "CSS", scss: "CSS", sh: "SH", c: "C", cpp: "C++", h: "H",
                  java: "JAVA", kt: "KT", swift: "SWFT", json: "{ }", md: "MD", pdf: "PDF", txt: "TXT", csv: "CSV",
                  yaml: "YAML", yml: "YAML", toml: "TOML", docx: "DOC", xlsx: "XLS", udf: "UDF", mp3: "♪", wav: "♪", ogg: "♪", flac: "♪" }
        return m[e] || e.toUpperCase().slice(0, 4)
    }
    function badgeColor(e) {
        var m = { py: "#6ea8e0", dart: "#4cc3f0", js: "#e8c547", ts: "#4f8cff", tsx: "#4f8cff", jsx: "#e8c547",
                  qml: "#41cd52", html: "#f0795a", htm: "#f0795a", css: "#a78bfa", rs: "#e0935a", go: "#4fd1c5",
                  json: "#4fd1a8", md: "#b9a2ff", pdf: "#f07a7a", mp3: "#e8b866", wav: "#e8b866", ogg: "#e8b866" }
        return Qt.color(m[e] || (Theme.dark ? "#9aa0b0" : "#6b7083"))
    }

    // ---------------- parçalar ----------------
    component Empty: Text {
        anchors.centerIn: parent
        color: Theme.muted; font.pixelSize: Theme.fs(12)
    }

    component IconBtn: Rectangle {
        id: ib
        property string glyph: ""
        property string tip: ""
        property bool danger: false
        readonly property color fg: ma.containsMouse ? (danger ? Theme.danger : Theme.text) : Theme.muted
        signal clicked
        width: 30; height: 30; radius: 9
        color: ma.containsMouse ? (danger ? Qt.rgba(0.95, 0.3, 0.3, 0.12) : Theme.cardHi) : "transparent"
        Behavior on color { ColorAnimation { duration: 120 } }
        Text { anchors.centerIn: parent; anchors.verticalCenterOffset: -1; text: ib.glyph; color: ib.fg; font.pixelSize: Theme.fs(18) }
        MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: ib.clicked() }
        ToolTip.visible: ma.containsMouse && tip !== ""; ToolTip.delay: 400; ToolTip.text: tip
    }

    // simge: çalışırken dönen yay, takılınca amber nefes, sözü kapalıyken soluk
    component Avatar: Item {
        id: av
        property real size: 32
        property string name
        property color tint
        property string state_: "idle"
        property bool stuck: false
        property bool muted: false
        width: size + 8; height: size + 8
        Shape {
            anchors.fill: parent
            visible: av.state_ === "running" && !av.stuck
            preferredRendererType: Shape.CurveRenderer
            RotationAnimation on rotation { running: av.state_ === "running" && !av.stuck; from: 0; to: 360; duration: 1100; loops: Animation.Infinite }
            ShapePath {
                strokeColor: av.tint; strokeWidth: 2; fillColor: "transparent"; capStyle: ShapePath.RoundCap
                PathAngleArc { centerX: av.width / 2; centerY: av.height / 2; radiusX: av.width / 2 - 1.5; radiusY: av.height / 2 - 1.5; startAngle: 0; sweepAngle: 110 }
            }
        }
        Rectangle {
            anchors.fill: parent; radius: width / 2
            visible: av.stuck; color: "transparent"; border.color: "#e3a547"; border.width: 2
            SequentialAnimation on opacity { running: av.stuck; loops: Animation.Infinite
                NumberAnimation { to: 0.25; duration: 1100; easing.type: Easing.InOutSine }
                NumberAnimation { to: 0.9; duration: 1100; easing.type: Easing.InOutSine } }
        }
        Rectangle {
            anchors.centerIn: parent; width: av.size; height: av.size; radius: av.size / 2
            color: av.tint
            opacity: av.state_ === "running" ? 1 : av.muted || av.state_ === "off" || av.state_ === "missing" ? 0.35 : 0.72
            Behavior on opacity { NumberAnimation { duration: 200 } }
            Text { anchors.centerIn: parent; text: av.name.charAt(0); color: "white"; font.weight: Font.Bold; font.pixelSize: Theme.fs(av.size > 30 ? 12.5 : 11) }
        }
    }

    component AgentRow: Rectangle {
        id: row
        property var a
        property var s
        readonly property bool running: s.state === "running"
        readonly property bool hov: rma.containsMouse || stopMa.containsMouse
        height: col.implicitHeight + 18; radius: 12
        color: hov ? Theme.cardHi : "transparent"
        Behavior on color { ColorAnimation { duration: 140 } }
        MouseArea { id: rma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                    onClicked: room.poke(row.a.key) }
        ToolTip.visible: rma.containsMouse && !row.running; ToolTip.delay: 700; ToolTip.text: "Söz ver"
        RowLayout {
            id: top
            x: 8; y: 9; width: parent.width - 16
            spacing: 10
            Avatar { Layout.alignment: Qt.AlignTop; size: 30; name: row.a.name; tint: row.a.color; state_: row.s.state || "idle"
                     stuck: !!row.s.stuck; muted: !!row.s.muted }
            ColumnLayout {
                id: col
                Layout.fillWidth: true; spacing: 2
                RowLayout {
                    spacing: 7
                    Text { text: row.a.name; color: Theme.text; font.pixelSize: Theme.fs(13); font.weight: Font.DemiBold }
                    Text { Layout.fillWidth: true; elide: Text.ElideRight; color: Theme.muted; font.pixelSize: Theme.fs(11)
                           text: (win.shortModel(row.a.model) || "varsayılan model") + (row.a.effort ? " · " + row.a.effort : "") }
                    Text {
                        visible: !row.hov || !row.running
                        text: row.running ? pn.elapsed(row.s.since) : ""
                        color: row.s.stuck ? "#e3a547" : Theme.textDim; font.pixelSize: Theme.fs(11.5); font.features: { "tnum": 1 }
                    }
                }
                Text {
                    Layout.fillWidth: true; elide: Text.ElideRight
                    font.pixelSize: Theme.fs(11.5)
                    color: row.running ? Theme.textDim : Theme.muted
                    text: row.s.state === "off" ? "devre dışı"
                        : row.s.state === "missing" ? "komut bulunamadı"
                        : row.running ? (row.s.cmd ? "› " + row.s.cmd : row.s.act || "düşünüyor…")
                        : (row.s.muted ? "sözü kapalı · " : "boşta") + (row.s.act && !row.s.muted ? " · " + row.s.act : "")
                    SequentialAnimation on opacity {   // çalışırken hafif nabız
                        running: row.running && !row.s.stuck; loops: Animation.Infinite
                        onRunningChanged: if (!running) parent.opacity = 1
                        NumberAnimation { to: 0.55; duration: 900; easing.type: Easing.InOutSine }
                        NumberAnimation { to: 1; duration: 900; easing.type: Easing.InOutSine }
                    }
                }
                Text {
                    visible: text !== ""
                    Layout.fillWidth: true; elide: Text.ElideRight
                    text: win.rolesOf(row.a.key); color: Theme.userHi; font.pixelSize: Theme.fs(10.5)
                }
                Text {
                    visible: !!usage(row.a.key)
                    text: usage(row.a.key); color: win.quotaFull(row.a.key) ? Theme.danger : Theme.muted
                    font.pixelSize: Theme.fs(10.5)
                }
                // takılma notu
                Rectangle {
                    visible: !!row.s.stuck
                    Layout.fillWidth: true; Layout.topMargin: 6
                    implicitHeight: stuckRow.implicitHeight + 16; radius: 10
                    color: Qt.rgba(0.89, 0.65, 0.28, Theme.dark ? 0.09 : 0.12)
                    RowLayout {
                        id: stuckRow
                        x: 10; y: 8; width: parent.width - 20; spacing: 8
                        Text { Layout.fillWidth: true; wrapMode: Text.WordWrap; font.pixelSize: Theme.fs(11.5)
                               color: Theme.dark ? "#dcbf8f" : "#8a5a12"
                               text: pn.mins(row.s.cmdSecs) + "'dır aynı komutta bekliyor" }
                        Rectangle {
                            implicitWidth: cutT.implicitWidth + 16; implicitHeight: 26; radius: 8
                            color: cutMa.containsMouse ? Qt.rgba(1, 1, 1, Theme.dark ? 0.14 : 0.5) : Qt.rgba(1, 1, 1, Theme.dark ? 0.08 : 0.35)
                            Text { id: cutT; anchors.centerIn: parent; text: "Komutu kes"; color: Theme.text; font.pixelSize: Theme.fs(11.5); font.weight: Font.Medium }
                            MouseArea { id: cutMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                        onClicked: room.cutCommand(row.a.key) }
                            ToolTip.visible: cutMa.containsMouse; ToolTip.delay: 400
                            ToolTip.text: "Yalnız takılan komutu durdurur; " + row.a.name + " devam eder.\n" + row.s.cmd
                        }
                    }
                }
            }
        }
        // sağda, üstüne gelince: durdur (çalışırken) ya da sözü kapat/aç (boştayken)
        Rectangle {
            id: stopB
            visible: (row.hov) && row.s.state !== "off" && row.s.state !== "missing"
            anchors.right: parent.right; anchors.rightMargin: 8; y: 9
            width: row.running ? 28 : muteT.implicitWidth + 16; height: 26; radius: 8
            color: stopMa.containsMouse ? (row.running ? Qt.rgba(0.95, 0.3, 0.3, 0.16) : Theme.card) : (Theme.dark ? "#262a35" : "#e6e8ef")
            Rectangle { visible: row.running; anchors.centerIn: parent; width: 9; height: 9; radius: 2
                        color: stopMa.containsMouse ? Theme.danger : Theme.text }
            Text { id: muteT; visible: !row.running; anchors.centerIn: parent; font.pixelSize: Theme.fs(11)
                   text: row.s.muted ? "Sözü aç" : "Sustur"; color: Theme.text }
            MouseArea { id: stopMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: row.running ? room.stopAgent(row.a.key) : room.toggleMute(row.a.key) }
            ToolTip.visible: stopMa.containsMouse; ToolTip.delay: 400
            ToolTip.text: row.running ? row.a.name + "'i durdur" :
                          row.s.muted ? "Yeniden turlara katılsın" : "Yeni turlara katılmasın; @ ile ya da adına tıklayınca yine konuşur"
        }
    }

    function shortModel(m) {
        if (!m) return "varsayılan model"
        return m.replace(/^claude-/, "").replace(/-(\d+)-(\d+)$/, " $1.$2").replace(/^gemini-/, "")
    }
    function usage(key) { var u = win.usageText(key); return win.quotaFull(key) ? "kota doldu" : u }
}
