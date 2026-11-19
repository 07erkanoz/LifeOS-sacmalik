import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Roller: ön tanımlı olarak kapalı. Önce roller gelir (hazır şablondan ya da elle), sonra her role odadaki ajanlar
// atanır: bir role birden çok ajan, bir ajana birden çok rol. Rolü olmayan ajan rolsüz konuşur.
// Kaydedince odaya görünür yazılır; roller yetki değil sorumluluk alanıdır, ortak karar kuralı sürer.
Popup {
    id: d
    modal: true
    anchors.centerIn: Overlay.overlay
    width: Math.min(680, win.width - 80)
    height: Math.min(col.implicitHeight + 200, win.height - 80)
    padding: 22
    property bool on: false
    property string template: ""
    property var list: []              // [{title, talk, prod, agents: [key]}]
    readonly property var agents: (win.cfg.agents || []).filter(function(a) { return a.enabled })

    onAboutToShow: {
        naming = false
        var r = room.roles
        on = r.on; template = r.template || ""
        list = JSON.parse(JSON.stringify(r.list || []))
    }
    function set(i, field, v) { var l = list.slice(); l[i] = Object.assign({}, l[i]); l[i][field] = v; list = l }
    function toggleAgent(i, key) {
        var a = (list[i].agents || []).slice(), j = a.indexOf(key)
        if (j >= 0) a.splice(j, 1); else a.push(key)
        set(i, "agents", a)
    }
    // şablon: rolleri getirir; ajanları sırayla önerir, fazla ajan son role eklenir (sonra değiştirilebilir)
    function useTemplate(t) {
        template = t.id; on = true
        var l = []
        for (var i = 0; i < t.roles.length; i++)
            l.push({ title: t.roles[i].title, talk: t.roles[i].talk, prod: t.roles[i].prod,
                     agents: list[i] && list[i].agents && list[i].agents.length ? list[i].agents.slice() : [] })
        var used = {}
        for (i = 0; i < l.length; i++) for (var k = 0; k < l[i].agents.length; k++) used[l[i].agents[k]] = true
        var free = agents.filter(function(a) { return !used[a.key] })
        for (i = 0; i < l.length && free.length; i++) if (!l[i].agents.length) l[i].agents.push(free.shift().key)
        while (free.length && l.length) l[l.length - 1].agents.push(free.shift().key)
        list = l
    }
    property bool naming: false
    function saveTemplate() {
        var roles = list.filter(function(r) { return r.title || r.talk || r.prod })
        if (!tname.text.trim()) { win.status = "Şablona bir ad verin"; return }
        if (!roles.length) { win.status = "Önce en az bir rol yazın"; return }
        var id = room.saveRoleTemplate(tname.text, roles)
        if (id) { template = id; naming = false }
    }
    function addRole() { on = true; template = template || "elle"; list = list.concat([{ title: "", talk: "", prod: "", agents: [] }]) }
    function removeRole(i) { var l = list.slice(); l.splice(i, 1); list = l }
    readonly property int unassigned: list.filter(function(r) { return !(r.agents || []).length }).length
    readonly property var roleless: agents.filter(function(a) { return !list.some(function(r) { return (r.agents || []).indexOf(a.key) >= 0 }) })

    enter: Transition { ParallelAnimation {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 160 }
        NumberAnimation { property: "scale"; from: 0.97; to: 1; duration: 200; easing.type: Easing.OutCubic } } }
    background: Rectangle { radius: 16; color: Theme.panel; border.color: Theme.line }
    Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.45) }

    contentItem: ColumnLayout {
        spacing: 14
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                Layout.fillWidth: true; spacing: 3
                Text { text: "Roller"; color: Theme.text; font.pixelSize: Theme.fs(18); font.weight: Font.Bold }
                Text { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: Theme.fs(12)
                       text: "Yalnız bu sohbet için. Bir şablon seçin ya da rol ekleyin, sonra her role ajan atayın; bir role birden çok ajan atanabilir. Rol yetki değil, sorumluluk alanıdır: kimse yönetici olmaz, ortak karar yine açık destekle alınır." }
            }
            Switch { checked: d.on; onToggled: { d.on = checked; if (checked && !d.list.length) d.addRole() } }
        }

        Flow {
            Layout.fillWidth: true
            spacing: 6
            opacity: d.on ? 1 : 0.4; enabled: d.on
            Repeater {
                model: room.roleTemplates
                Rectangle {
                    id: chip
                    readonly property bool sel: d.template === modelData.id
                    readonly property bool hov: tma.containsMouse || xma.containsMouse
                    implicitWidth: tt.implicitWidth + 24 + (modelData.own ? 18 : 0); implicitHeight: 30; radius: 15
                    color: sel ? Qt.rgba(Theme.user.r, Theme.user.g, Theme.user.b, 0.22) : hov ? Theme.cardHi : "transparent"
                    border.color: sel ? Theme.user : modelData.own ? Qt.rgba(Theme.user.r, Theme.user.g, Theme.user.b, 0.45) : Theme.line
                    Behavior on color { ColorAnimation { duration: 120 } }
                    Text { id: tt; x: 12; anchors.verticalCenter: parent.verticalCenter; text: modelData.name
                           color: sel ? Theme.text : Theme.textDim; font.pixelSize: Theme.fs(12) }
                    MouseArea { id: tma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: d.useTemplate(modelData) }
                    // kendi şablonu: silinebilir
                    Text {
                        visible: modelData.own
                        anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter
                        text: "✕"; font.pixelSize: Theme.fs(10.5)
                        color: xma.containsMouse ? Theme.danger : chip.hov ? Theme.textDim : Theme.muted
                        MouseArea { id: xma; anchors.fill: parent; anchors.margins: -5; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                    onClicked: { if (d.template === modelData.id) d.template = "elle"; room.deleteRoleTemplate(modelData.id) } }
                        ToolTip.visible: xma.containsMouse; ToolTip.delay: 300; ToolTip.text: "Şablonu sil"
                    }
                    ToolTip.visible: tma.containsMouse && modelData.own; ToolTip.delay: 600
                    ToolTip.text: "Kendi şablonunuz: " + modelData.roles.map(function(r) { return r.title }).join(", ")
                }
            }
            // şimdiki rolleri şablon olarak sakla
            Rectangle {
                visible: !d.naming
                implicitWidth: st.implicitWidth + 24; implicitHeight: 30; radius: 15
                color: sma.containsMouse ? Theme.cardHi : "transparent"
                border.color: Theme.line; border.width: 1
                Text { id: st; anchors.centerIn: parent; text: "＋ Şablon olarak kaydet"; color: Theme.textDim; font.pixelSize: Theme.fs(12) }
                MouseArea { id: sma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                            onClicked: { d.naming = true; tname.text = ""; tname.forceActiveFocus() } }
                ToolTip.visible: sma.containsMouse; ToolTip.delay: 400
                ToolTip.text: "Aşağıdaki rolleri (adları ve açıklamalarıyla) başka sohbetlerde de seçmek için saklar. Ajan atamaları saklanmaz."
            }
            Row {
                visible: d.naming
                spacing: 6
                Field { id: tname; width: 200; placeholderText: "Şablonun adı"; implicitHeight: 30
                        onAccepted: d.saveTemplate(); Keys.onEscapePressed: d.naming = false }
                GhostButton { text: "Kaydet"; implicitHeight: 30; onClicked: d.saveTemplate() }
                GhostButton { text: "Vazgeç"; implicitHeight: 30; onClicked: d.naming = false }
            }
        }

        Flickable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredHeight: col.implicitHeight
            contentHeight: col.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            opacity: d.on ? 1 : 0.4; enabled: d.on
            ColumnLayout {
                id: col
                width: parent.width
                spacing: 10

                Repeater {
                    model: d.list.length
                    Rectangle {
                        id: card
                        required property int index
                        readonly property var r: d.list[index]
                        readonly property var picked: d.agents.filter(function(a) { return (card.r.agents || []).indexOf(a.key) >= 0 })
                        Layout.fillWidth: true
                        implicitHeight: g.implicitHeight + 26
                        radius: 12; color: Theme.card
                        border.color: picked.length ? Qt.rgba(Qt.color(picked[0].color).r, Qt.color(picked[0].color).g, Qt.color(picked[0].color).b, 0.4) : Theme.lineSoft
                        Behavior on border.color { ColorAnimation { duration: 150 } }
                        ColumnLayout {
                            id: g
                            x: 13; y: 13; width: parent.width - 26
                            spacing: 9
                            RowLayout {
                                Layout.fillWidth: true; spacing: 8
                                Field { Layout.fillWidth: true; text: card.r.title; placeholderText: "Rolün adı (ör. Görsel ve sahne)"
                                        font.weight: Font.DemiBold; onTextEdited: d.set(card.index, "title", text) }
                                GhostButton { text: "✕"; implicitWidth: 34; accent: "#ef4444"; onClicked: d.removeRole(card.index)
                                              ToolTip.visible: hovered; ToolTip.text: "Rolü kaldır" }
                            }
                            // bu rolü kimler üstlenir: odadaki ajanlar, birden çoğu seçilebilir
                            Flow {
                                Layout.fillWidth: true
                                spacing: 6
                                Text { text: "Ajanlar"; color: Theme.textDim; font.pixelSize: Theme.fs(12); height: 30; verticalAlignment: Text.AlignVCenter; rightPadding: 6 }
                                Repeater {
                                    model: d.agents
                                    Rectangle {
                                        readonly property bool sel: (card.r.agents || []).indexOf(modelData.key) >= 0
                                        implicitWidth: ar.implicitWidth + 22; implicitHeight: 30; radius: 15
                                        color: sel ? Qt.rgba(Qt.color(modelData.color).r, Qt.color(modelData.color).g, Qt.color(modelData.color).b, 0.22)
                                             : am.containsMouse ? Theme.cardHi : "transparent"
                                        border.color: sel ? modelData.color : Theme.line
                                        Behavior on color { ColorAnimation { duration: 120 } }
                                        Row {
                                            id: ar; anchors.centerIn: parent; spacing: 6
                                            Rectangle {
                                                width: 16; height: 16; radius: 8; anchors.verticalCenter: parent.verticalCenter
                                                color: parent.parent.sel ? modelData.color : "transparent"
                                                border.color: modelData.color; border.width: 1.5
                                                Text { anchors.centerIn: parent; text: parent.parent.parent.sel ? "✓" : ""; color: "white"; font.bold: true; font.pixelSize: Theme.fs(9) }
                                            }
                                            Text { text: modelData.name; color: parent.parent.sel ? Theme.text : Theme.textDim; font.pixelSize: Theme.fs(12); anchors.verticalCenter: parent.verticalCenter }
                                            Text { visible: !!modelData.model; text: win.shortModel(modelData.model); color: Theme.muted; font.pixelSize: Theme.fs(10.5); anchors.verticalCenter: parent.verticalCenter }
                                        }
                                        MouseArea { id: am; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                                    onClicked: d.toggleAgent(card.index, modelData.key) }
                                    }
                                }
                            }
                            GridLayout {
                                Layout.fillWidth: true
                                columns: 2; columnSpacing: 10; rowSpacing: 7
                                Text { text: "Tartışma"; color: Theme.textDim; font.pixelSize: Theme.fs(12); Layout.preferredWidth: 62 }
                                Field { Layout.fillWidth: true; text: card.r.talk; placeholderText: "Tartışmada neye bakar"
                                        onTextEdited: d.set(card.index, "talk", text) }
                                Text { text: "Üretim"; color: Theme.textDim; font.pixelSize: Theme.fs(12) }
                                Field { Layout.fillWidth: true; text: card.r.prod; placeholderText: "Üretimde hangi parçayı yapar"
                                        onTextEdited: d.set(card.index, "prod", text) }
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 40; radius: 12
                    color: addMa.containsMouse ? Theme.cardHi : "transparent"
                    border.color: Theme.line
                    Text { anchors.centerIn: parent; text: "＋  Rol ekle"; color: Theme.textDim; font.pixelSize: Theme.fs(12.5) }
                    MouseArea { id: addMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: d.addRole() }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text {
                Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: Theme.fs(11)
                text: !d.on ? "Roller kapalı. Kaydederseniz odaya \"roller kapatıldı\" yazılır."
                    : d.unassigned ? d.unassigned + " role ajan atanmadı; ajansız rol kaydedilmez."
                    : d.roleless.length ? "Rolsüz: " + d.roleless.map(function(a) { return a.name }).join(", ") + " (rolsüz konuşur)." : ""
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
