import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// İş bölümü ve roller: ön tanımlı olarak kapalı. Satırlarda işler (Plan, Kod, Görsel…; kendi işiniz de),
// sütunlarda odadaki ajanlar: hücreye tıklamak işi o ajana verir. Bir işe birden çok ajan, bir ajana birden çok iş.
// Açıklama isteğe bağlı: yazılmazsa hazır işin varsayılan anlamı kullanılır. Şablonlar ayrıntılı rolleri doldurur.
// Kaydedince odaya görünür yazılır ve ajanlara oda bilgisiyle gider; ortak karar kuralı sürer.
Popup {
    id: d
    modal: true
    anchors.centerIn: Overlay.overlay
    width: Math.min(Math.max(640, 230 + agents.length * 78 + 90), win.width - 80)
    height: Math.min(body.implicitHeight + 250, win.height - 80)
    padding: 22
    property bool on: false
    property string template: ""
    property var list: []              // [{title, talk, prod, agents: [key]}]
    property var expanded: ({})        // satır → açıklama alanları açık mı
    property bool naming: false
    readonly property var agents: (win.cfg.agents || []).filter(function(a) { return a.enabled })
    readonly property real cellW: 78

    function isTask(title) { return room.tasks.some(function(t) { return t.title.toLowerCase() === (title || "").toLowerCase() }) }
    function taskOf(title) { for (var i = 0; i < room.tasks.length; i++) if (room.tasks[i].title.toLowerCase() === (title || "").toLowerCase()) return room.tasks[i]; return null }
    onAboutToShow: {
        naming = false; expanded = ({})
        var r = room.roles
        on = r.on; template = r.template || ""
        list = JSON.parse(JSON.stringify(r.list || []))
        if (!list.length)                  // ilk açılış: en sık işler, ajansız
            list = ["Plan", "Kod", "Görsel", "Ses", "Test"].map(function(t) { return { title: t, talk: "", prod: "", agents: [] } })
    }
    function set(i, field, v) { var l = list.slice(); l[i] = Object.assign({}, l[i]); l[i][field] = v; list = l }
    function toggleAgent(i, key) {
        var a = (list[i].agents || []).slice(), j = a.indexOf(key)
        if (j >= 0) a.splice(j, 1); else a.push(key)
        set(i, "agents", a); on = true
    }
    function addTask(title) {
        on = true
        list = list.concat([{ title: title || "", talk: "", prod: "", agents: [] }])
        if (!title) Qt.callLater(function() { var e = Object.assign({}, expanded); e[list.length - 1] = true; expanded = e })
    }
    function removeRow(i) {
        var l = list.slice(); l.splice(i, 1); list = l
        var e = {}; for (var k in expanded) { var n = +k; if (n < i) e[n] = expanded[k]; else if (n > i) e[n - 1] = expanded[k] } expanded = e
    }
    function toggleOpen(i) { var e = Object.assign({}, expanded); e[i] = !e[i]; expanded = e }
    // şablon: ayrıntılı rolleri getirir; ajanları sırayla önerir, fazla ajan son role eklenir (sonra değiştirilebilir)
    function useTemplate(t) {
        template = t.id; on = true
        var l = []
        for (var i = 0; i < t.roles.length; i++)
            l.push({ title: t.roles[i].title, talk: t.roles[i].talk, prod: t.roles[i].prod, agents: [] })
        var free = agents.slice()
        for (i = 0; i < l.length && free.length; i++) l[i].agents.push(free.shift().key)
        while (free.length && l.length) l[l.length - 1].agents.push(free.shift().key)
        list = l; expanded = ({})
    }
    function saveTemplate() {
        var roles = list.filter(function(r) { return r.title || r.talk || r.prod })
        if (!tname.text.trim()) { win.status = "Şablona bir ad verin"; return }
        if (!roles.length) { win.status = "Önce en az bir iş yazın"; return }
        var id = room.saveRoleTemplate(tname.text, roles)
        if (id) { template = id; naming = false }
    }
    readonly property int unassigned: list.filter(function(r) { return r.title && !(r.agents || []).length }).length
    readonly property var unusedTasks: room.tasks.filter(function(t) { return !list.some(function(r) { return (r.title || "").toLowerCase() === t.title.toLowerCase() }) })

    enter: Transition { ParallelAnimation {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 160 }
        NumberAnimation { property: "scale"; from: 0.97; to: 1; duration: 200; easing.type: Easing.OutCubic } } }
    background: Rectangle { radius: 16; color: Theme.panel; border.color: Theme.line }
    Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.45) }

    contentItem: ColumnLayout {
        spacing: 12
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                Layout.fillWidth: true; spacing: 3
                Text { text: "İş bölümü"; color: Theme.text; font.pixelSize: Theme.fs(18); font.weight: Font.Bold }
                Text { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: Theme.fs(12)
                       text: "Yalnız bu sohbet için. Bir işi bir ajana vermek için kesişimine tıklayın; bir işe birden çok ajan verilebilir. Yetki değil, sorumluluk alanıdır: ortak karar yine açık destekle alınır." }
            }
            Switch { checked: d.on; onToggled: d.on = checked }
        }

        // şablonlar (ayrıntılı roller) ve kendi şablonlarınız
        Flow {
            Layout.fillWidth: true
            spacing: 6
            opacity: d.on ? 1 : 0.4; enabled: d.on
            Text { text: "Şablon"; color: Theme.muted; font.pixelSize: Theme.fs(11.5); height: 28; verticalAlignment: Text.AlignVCenter; rightPadding: 4 }
            Repeater {
                model: room.roleTemplates
                Rectangle {
                    id: chip
                    readonly property bool sel: d.template === modelData.id
                    readonly property bool hov: tma.containsMouse || xma.containsMouse
                    implicitWidth: tt.implicitWidth + 22 + (modelData.own ? 18 : 0); implicitHeight: 28; radius: 14
                    color: sel ? Qt.rgba(Theme.user.r, Theme.user.g, Theme.user.b, 0.22) : hov ? Theme.cardHi : "transparent"
                    border.color: sel ? Theme.user : modelData.own ? Qt.rgba(Theme.user.r, Theme.user.g, Theme.user.b, 0.45) : Theme.line
                    Behavior on color { ColorAnimation { duration: 120 } }
                    Text { id: tt; x: 11; anchors.verticalCenter: parent.verticalCenter; text: modelData.name
                           color: sel ? Theme.text : Theme.textDim; font.pixelSize: Theme.fs(11.5) }
                    MouseArea { id: tma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: d.useTemplate(modelData) }
                    Text {
                        visible: modelData.own
                        anchors.right: parent.right; anchors.rightMargin: 9; anchors.verticalCenter: parent.verticalCenter
                        text: "✕"; font.pixelSize: Theme.fs(10)
                        color: xma.containsMouse ? Theme.danger : chip.hov ? Theme.textDim : Theme.muted
                        MouseArea { id: xma; anchors.fill: parent; anchors.margins: -5; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                    onClicked: { if (d.template === modelData.id) d.template = ""; room.deleteRoleTemplate(modelData.id) } }
                        ToolTip.visible: xma.containsMouse; ToolTip.delay: 300; ToolTip.text: "Şablonu sil"
                    }
                    ToolTip.visible: tma.containsMouse; ToolTip.delay: 600
                    ToolTip.text: modelData.roles.map(function(r) { return r.title }).join(" · ")
                }
            }
            Rectangle {
                visible: !d.naming
                implicitWidth: st.implicitWidth + 22; implicitHeight: 28; radius: 14
                color: sma.containsMouse ? Theme.cardHi : "transparent"; border.color: Theme.line
                Text { id: st; anchors.centerIn: parent; text: "＋ Şablon olarak kaydet"; color: Theme.textDim; font.pixelSize: Theme.fs(11.5) }
                MouseArea { id: sma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                            onClicked: { d.naming = true; tname.text = ""; tname.forceActiveFocus() } }
                ToolTip.visible: sma.containsMouse; ToolTip.delay: 400
                ToolTip.text: "Bu işleri (adları ve açıklamalarıyla) başka sohbetlerde de seçmek için saklar. Ajan atamaları saklanmaz."
            }
            Row {
                visible: d.naming
                spacing: 6
                Field { id: tname; width: 190; placeholderText: "Şablonun adı"; implicitHeight: 28
                        onAccepted: d.saveTemplate(); Keys.onEscapePressed: d.naming = false }
                GhostButton { text: "Kaydet"; implicitHeight: 28; onClicked: d.saveTemplate() }
                GhostButton { text: "Vazgeç"; implicitHeight: 28; onClicked: d.naming = false }
            }
        }

        // tablo
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredHeight: body.implicitHeight + 2
            radius: 12; color: Theme.card; border.color: Theme.lineSoft
            clip: true
            opacity: d.on ? 1 : 0.45; enabled: d.on
            Behavior on opacity { NumberAnimation { duration: 150 } }

            Flickable {
                anchors.fill: parent
                contentHeight: body.implicitHeight
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                ColumnLayout {
                    id: body
                    width: parent.width
                    spacing: 0

                    // başlık satırı: ajanlar
                    RowLayout {
                        Layout.fillWidth: true; Layout.preferredHeight: 58
                        spacing: 0
                        Text { Layout.fillWidth: true; Layout.leftMargin: 16; text: "İş"; color: Theme.muted; font.pixelSize: Theme.fs(11); font.letterSpacing: 0.4 }
                        Repeater {
                            model: d.agents
                            Item {
                                Layout.preferredWidth: d.cellW; Layout.fillHeight: true
                                Column {
                                    anchors.centerIn: parent; spacing: 3
                                    Rectangle { anchors.horizontalCenter: parent.horizontalCenter; width: 22; height: 22; radius: 11; color: modelData.color
                                        Text { anchors.centerIn: parent; text: modelData.name.charAt(0); color: "white"; font.bold: true; font.pixelSize: Theme.fs(10) } }
                                    Text { anchors.horizontalCenter: parent.horizontalCenter; width: d.cellW - 8; horizontalAlignment: Text.AlignHCenter
                                           text: modelData.name; color: Theme.textDim; font.pixelSize: Theme.fs(11); elide: Text.ElideRight }
                                }
                                ToolTip.visible: hh.containsMouse; ToolTip.delay: 400
                                ToolTip.text: modelData.name + (modelData.model ? " · " + modelData.model : "") + (modelData.effort ? " · " + modelData.effort : "")
                                MouseArea { id: hh; anchors.fill: parent; hoverEnabled: true }
                            }
                        }
                        Item { Layout.preferredWidth: 72 }
                    }
                    Rectangle { Layout.fillWidth: true; height: 1; color: Theme.lineSoft }

                    Repeater {
                        model: d.list.length
                        ColumnLayout {
                            id: row
                            required property int index
                            readonly property var r: d.list[index]
                            readonly property var task: d.taskOf(r.title)
                            readonly property bool open: !!d.expanded[index]
                            Layout.fillWidth: true
                            spacing: 0
                            Rectangle {
                                Layout.fillWidth: true; Layout.preferredHeight: 46
                                color: rowMa.containsMouse ? Qt.rgba(1, 1, 1, Theme.dark ? 0.025 : 0.5) : "transparent"
                                MouseArea { id: rowMa; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                                RowLayout {
                                    anchors.fill: parent; spacing: 0
                                    // işin adı: düzenlenebilir, yazı gibi görünür
                                    TextField {
                                        id: tf
                                        Layout.fillWidth: true; Layout.leftMargin: 8
                                        text: row.r.title; placeholderText: "İşin adı (ör. Müzik)"
                                        placeholderTextColor: Theme.muted
                                        color: Theme.text; font.pixelSize: Theme.fs(13); font.weight: Font.Medium
                                        selectByMouse: true; leftPadding: 8
                                        background: Rectangle { radius: 7; color: tf.activeFocus ? Theme.bg : "transparent"
                                                                border.color: tf.activeFocus ? Theme.user : tf.hovered ? Theme.line : "transparent" }
                                        onTextEdited: d.set(row.index, "title", text)
                                        ToolTip.visible: hovered && !activeFocus && !!row.task && !(row.r.talk || row.r.prod); ToolTip.delay: 700
                                        ToolTip.text: row.task ? "Tartışma: " + row.task.talk + "\nÜretim: " + row.task.prod : ""
                                    }
                                    Repeater {
                                        model: d.agents
                                        Item {
                                            readonly property bool sel: (row.r.agents || []).indexOf(modelData.key) >= 0
                                            Layout.preferredWidth: d.cellW; Layout.fillHeight: true
                                            Rectangle {
                                                anchors.centerIn: parent
                                                width: 22; height: 22; radius: 11
                                                color: parent.sel ? modelData.color : cm.containsMouse ? Qt.rgba(Qt.color(modelData.color).r, Qt.color(modelData.color).g, Qt.color(modelData.color).b, 0.18) : "transparent"
                                                border.color: parent.sel ? modelData.color : cm.containsMouse ? modelData.color : Theme.line
                                                border.width: 1.5
                                                scale: parent.sel ? 1 : 0.86
                                                Behavior on scale { NumberAnimation { duration: 160; easing.type: Easing.OutBack } }
                                                Behavior on color { ColorAnimation { duration: 140 } }
                                                Text { anchors.centerIn: parent; visible: parent.parent.sel; text: "✓"; color: "white"; font.pixelSize: Theme.fs(11); font.bold: true }
                                            }
                                            MouseArea { id: cm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                                        onClicked: d.toggleAgent(row.index, modelData.key) }
                                            ToolTip.visible: cm.containsMouse; ToolTip.delay: 500
                                            ToolTip.text: (parent.sel ? "Bu işten çıkar: " : "Bu işi ver: ") + modelData.name
                                        }
                                    }
                                    // açıklama ve sil
                                    Row {
                                        Layout.preferredWidth: 72; spacing: 2
                                        Rectangle {
                                            width: 32; height: 28; radius: 7
                                            color: om.containsMouse ? Theme.cardHi : "transparent"
                                            Text { anchors.centerIn: parent; text: row.open ? "▴" : "✎"; font.pixelSize: Theme.fs(12)
                                                   color: (row.r.talk || row.r.prod) ? Theme.userHi : om.containsMouse ? Theme.text : Theme.muted }
                                            MouseArea { id: om; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: d.toggleOpen(row.index) }
                                            ToolTip.visible: om.containsMouse; ToolTip.delay: 400
                                            ToolTip.text: (row.r.talk || row.r.prod) ? "Açıklamayı düzenle" : "Açıklama ekle (isteğe bağlı)"
                                        }
                                        Rectangle {
                                            width: 32; height: 28; radius: 7
                                            color: dm.containsMouse ? Qt.rgba(0.95, 0.3, 0.3, 0.12) : "transparent"
                                            Text { anchors.centerIn: parent; text: "✕"; font.pixelSize: Theme.fs(11); color: dm.containsMouse ? Theme.danger : Theme.muted }
                                            MouseArea { id: dm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: d.removeRow(row.index) }
                                            ToolTip.visible: dm.containsMouse; ToolTip.delay: 400; ToolTip.text: "İşi kaldır"
                                        }
                                    }
                                }
                            }
                            // açıklama: isteğe bağlı, hazır işte boşsa varsayılan anlam gösterilir
                            GridLayout {
                                visible: row.open
                                Layout.fillWidth: true; Layout.leftMargin: 16; Layout.rightMargin: 16; Layout.bottomMargin: 10
                                columns: 2; columnSpacing: 10; rowSpacing: 6
                                Text { text: "Tartışma"; color: Theme.textDim; font.pixelSize: Theme.fs(11.5); Layout.preferredWidth: 60 }
                                Field { Layout.fillWidth: true; text: row.r.talk; implicitHeight: 30
                                        placeholderText: row.task ? row.task.talk : "Tartışmada neye bakar"
                                        onTextEdited: d.set(row.index, "talk", text) }
                                Text { text: "Üretim"; color: Theme.textDim; font.pixelSize: Theme.fs(11.5) }
                                Field { Layout.fillWidth: true; text: row.r.prod; implicitHeight: 30
                                        placeholderText: row.task ? row.task.prod : "Üretimde neyi yapar"
                                        onTextEdited: d.set(row.index, "prod", text) }
                            }
                            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.lineSoft; opacity: 0.6 }
                        }
                    }

                    // iş ekle: kullanılmayan hazır işler ve kendi işiniz
                    Flow {
                        Layout.fillWidth: true; Layout.margins: 12
                        spacing: 6
                        Text { text: "Ekle"; color: Theme.muted; font.pixelSize: Theme.fs(11.5); height: 28; verticalAlignment: Text.AlignVCenter; rightPadding: 4 }
                        Repeater {
                            model: d.unusedTasks
                            Rectangle {
                                implicitWidth: at.implicitWidth + 22; implicitHeight: 28; radius: 14
                                color: aMa.containsMouse ? Theme.cardHi : "transparent"; border.color: Theme.line
                                Text { id: at; anchors.centerIn: parent; text: "＋ " + modelData.title; color: Theme.textDim; font.pixelSize: Theme.fs(11.5) }
                                MouseArea { id: aMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: d.addTask(modelData.title) }
                            }
                        }
                        Rectangle {
                            implicitWidth: ot.implicitWidth + 22; implicitHeight: 28; radius: 14
                            color: oMa.containsMouse ? Qt.rgba(Theme.user.r, Theme.user.g, Theme.user.b, 0.18) : "transparent"
                            border.color: Qt.rgba(Theme.user.r, Theme.user.g, Theme.user.b, 0.55)
                            Text { id: ot; anchors.centerIn: parent; text: "＋ Kendi işin"; color: Theme.text; font.pixelSize: Theme.fs(11.5) }
                            MouseArea { id: oMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: d.addTask("") }
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text {
                Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: Theme.fs(11)
                text: !d.on ? "Kapalı: kimsenin işi ya da rolü yok."
                    : d.unassigned ? d.unassigned + " işe ajan verilmedi; ajansız iş kaydedilmez." : "Kaydedince odaya bir satır düşer ve ajanlar kendi işlerini görür."
            }
            GhostButton { text: "Vazgeç"; onClicked: d.close() }
            Button {
                id: save
                text: "Kaydet"
                implicitHeight: 34; implicitWidth: 96
                contentItem: Text { text: save.text; color: "white"; font.pixelSize: Theme.fs(13); font.bold: true
                                    horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                background: Rectangle { radius: 9; color: save.down ? Qt.darker(Theme.user, 1.2) : Theme.user }
                onClicked: { room.setRoles({ on: d.on, template: d.template, list: d.list }); d.close() }
            }
        }
    }
}
