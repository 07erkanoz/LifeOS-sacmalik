import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Drawer {
    id: d
    edge: Qt.RightEdge
    modal: true
    property var draft: ({})
    property var tests: ({})
    property var models: ({})
    // key -> {models: [], efforts: []}

    onAboutToShow: {
        draft = JSON.parse(JSON.stringify(room.settings)); tests = {}
        for (var i = 0; i < draft.agents.length; i++) room.fetchModels(draft.agents[i].key)
    }

    // yeni nesne üret ki bağlamalar (seçili effort/renk vb.) güncellensin
    function setAgent(i, k, v) {
        var ag = draft.agents.slice()
        ag[i] = Object.assign({}, ag[i]); ag[i][k] = v
        var nd = Object.assign({}, draft); nd.agents = ag
        draft = nd
    }

    Connections {
        target: room
        function onModelsReady(key, ms, efs) {
            var m = Object.assign({}, d.models); m[key] = { models: ms, efforts: efs }; d.models = m
        }
        function onTestResult(key, ok, out) {
            var t = Object.assign({}, d.tests); t[key] = { ok: ok, out: out, running: false }; d.tests = t
        }
    }

    background: Rectangle {
        color: Theme.panel
        Rectangle { width: 1; height: parent.height; color: Theme.line }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 22
        spacing: 16

        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                spacing: 2
                Text { text: "Ayarlar"; color: Theme.text; font.pixelSize: Theme.fs(20); font.bold: true }
                Text { text: "CLI bağlantıları ve proje klasörü"; color: Theme.muted; font.pixelSize: Theme.fs(12) }
            }
            Item { Layout.fillWidth: true }
            GhostButton { text: "✕"; implicitWidth: 34; onClicked: d.close() }
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true

            ColumnLayout {
                width: parent.width
                spacing: 14

                // ---- oda ----
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: roomCol.implicitHeight + 28
                    radius: 14; color: Theme.card; border.color: Theme.line
                    ColumnLayout {
                        id: roomCol
                        anchors.fill: parent; anchors.margins: 14
                        spacing: 10
                        Text { text: "ODA"; color: Theme.muted; font.pixelSize: Theme.fs(10); font.letterSpacing: 1.5 }
                        GridLayout {
                            columns: 2; columnSpacing: 12; rowSpacing: 8
                            Layout.fillWidth: true
                            Text { text: "Senin adın"; color: Theme.textDim; font.pixelSize: Theme.fs(12); wrapMode: Text.WordWrap; Layout.preferredWidth: 190 }
                            Field { Layout.fillWidth: true; text: d.draft.userName || ""; onTextEdited: d.draft.userName = text }
                            Text { text: "Yazı boyutu"; color: Theme.textDim; font.pixelSize: Theme.fs(12); wrapMode: Text.WordWrap; Layout.preferredWidth: 190 }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6
                                readonly property real v: d.draft.fontScale || 1.0
                                GhostButton { text: "A−"; implicitWidth: 40
                                              onClicked: { var nd = Object.assign({}, d.draft); nd.fontScale = Math.max(0.8, Math.round((parent.v - 0.1) * 10) / 10); d.draft = nd } }
                                Text { text: "%" + Math.round(parent.v * 100); color: Theme.text; font.pixelSize: Theme.fs(13)
                                       Layout.preferredWidth: 48; horizontalAlignment: Text.AlignHCenter }
                                GhostButton { text: "A+"; implicitWidth: 40
                                              onClicked: { var nd = Object.assign({}, d.draft); nd.fontScale = Math.min(1.6, Math.round((parent.v + 0.1) * 10) / 10); d.draft = nd } }
                                Text { text: "Ctrl + / Ctrl − / Ctrl 0"; color: Theme.muted; font.pixelSize: Theme.fs(11); Layout.leftMargin: 6
                                       Layout.fillWidth: true; elide: Text.ElideRight }
                            }
                            Text { text: "Proje klasörü"; color: Theme.textDim; font.pixelSize: Theme.fs(12); wrapMode: Text.WordWrap; Layout.preferredWidth: 190 }
                            RowLayout {
                                Layout.fillWidth: true; spacing: 6
                                Field { id: wd; Layout.fillWidth: true; text: d.draft.workDir || ""; onTextEdited: d.draft.workDir = text }
                                GhostButton { text: "Seç…"; onClicked: win.pickFolder(function(p) { d.draft.workDir = p; wd.text = p }) }
                            }
                            Text { text: "Döküm sınırı (karakter)"; color: Theme.textDim; font.pixelSize: Theme.fs(12); wrapMode: Text.WordWrap; Layout.preferredWidth: 190 }
                            Field { Layout.fillWidth: true; text: String(d.draft.maxChars || 60000)
                                    validator: IntValidator { bottom: 1000 }
                                    onTextEdited: d.draft.maxChars = parseInt(text) || 60000 }
                            Text { text: "Mesajın başına en fazla model çağrısı (0 = sınırsız)"; color: Theme.textDim; font.pixelSize: Theme.fs(12); wrapMode: Text.WordWrap; Layout.preferredWidth: 190 }
                            Field { Layout.fillWidth: true; text: String(d.draft.maxCalls === undefined ? 12 : d.draft.maxCalls)
                                    validator: IntValidator { bottom: 0 }
                                    onTextEdited: d.draft.maxCalls = parseInt(text) || 0 }
                            Text { text: "Antigravity komut zaman aşımı, saniye (0 = kapalı)"; color: Theme.textDim; font.pixelSize: Theme.fs(12); wrapMode: Text.WordWrap; Layout.preferredWidth: 190 }
                            Field { Layout.fillWidth: true; text: String(d.draft.cmdTimeout === undefined ? 180 : d.draft.cmdTimeout)
                                    validator: IntValidator { bottom: 0 }
                                    onTextEdited: d.draft.cmdTimeout = parseInt(text) || 0 }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            Switch {
                                checked: d.draft.pact !== false
                                onToggled: { var nd = Object.assign({}, d.draft); nd.pact = checked; d.draft = nd }
                            }
                            Text {
                                Layout.fillWidth: true; wrapMode: Text.WordWrap
                                color: Theme.textDim; font.pixelSize: Theme.fs(12)
                                text: "Oda anlaşması: Tartışma'da ilk mesajla \"ortak karar diye aktarırken kimin desteklediğini belirtin\", Üretim ilk açılınca \"üstlendiğin parçayı söyle, başkasının yazdığını onaysız ezme\" satırı odaya görünür düşer"
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            Switch {
                                checked: d.draft.liveRelay !== false
                                onToggled: { var nd = Object.assign({}, d.draft); nd.liveRelay = checked; d.draft = nd }
                            }
                            Text {
                                Layout.fillWidth: true; wrapMode: Text.WordWrap
                                color: Theme.textDim; font.pixelSize: Theme.fs(12)
                                text: "Canlı iletim: bir ajan konuşunca çalışmakta olan diğerleri bunu hemen alır. Kapatınca birbirlerini sıraları gelince toplu okurlar; daha az tur, daha az kota. Senin mesajın her zaman anında gider."
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            Switch {
                                checked: d.draft.leanTools !== false
                                onToggled: { var nd = Object.assign({}, d.draft); nd.leanTools = checked; d.draft = nd }
                            }
                            Text {
                                Layout.fillWidth: true; wrapMode: Text.WordWrap
                                color: Theme.textDim; font.pixelSize: Theme.fs(12)
                                text: "Yalın araç profili: Claude ve Codex senin kişisel bağlayıcıların (Gmail, Takvim, Drive…) ve MCP sunucuların olmadan açılır. Dosya, komut, web araması ve Codex'in tarayıcısı kalır. Kapatınca kendi kurulumunla açılırlar."
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            Switch {
                                checked: d.draft.parallel !== false
                                onToggled: { var nd = Object.assign({}, d.draft); nd.parallel = checked; d.draft = nd }
                            }
                            Text {
                                Layout.fillWidth: true; wrapMode: Text.WordWrap
                                color: Theme.textDim; font.pixelSize: Theme.fs(12)
                                text: "Aynı anda söz: yeni mesajda üçü birden çağrılır; biri konuşunca çalışmakta olanlara anında iletilir (Claude çalışırken alır, Codex ve Antigravity işini bitirince)"
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            Switch {
                                checked: d.draft.keepSessions !== false
                                onToggled: { var nd = Object.assign({}, d.draft); nd.keepSessions = checked; d.draft = nd }
                            }
                            Text {
                                Layout.fillWidth: true; wrapMode: Text.WordWrap
                                color: Theme.textDim; font.pixelSize: Theme.fs(12)
                                text: "Bağlam hafızası: her ajanın CLI oturumunu sürdür (okuduklarını, yaptıklarını unutmasın; her seferinde yalnızca yeni mesajları alır)"
                            }
                        }
                        Text {
                            Layout.fillWidth: true; wrapMode: Text.WordWrap
                            color: Theme.muted; font.pixelSize: Theme.fs(11)
                            text: "Üç ajan da bu klasörde çalışır; dosya üretirlerse buraya yazarlar. Ajanlara giden tek şey: konum, odadakiler ve \"Ad: mesaj\" dökümü. Rol, kural, talimat yok."
                        }
                    }
                }

                // ---- ajanlar ----
                Repeater {
                    model: d.draft.agents ? d.draft.agents.length : 0
                    Rectangle {
                        id: card
                        required property int index
                        readonly property var a: d.draft.agents[index]
                        readonly property var t: d.tests[a.key]
                        readonly property bool isAgy: a.key === "agy" || a.command.indexOf("agy") === 0
                        Layout.fillWidth: true
                        implicitHeight: col.implicitHeight + 28
                        radius: 14; color: Theme.card
                        border.color: Qt.rgba(Qt.color(a.color).r, Qt.color(a.color).g, Qt.color(a.color).b, 0.4)

                        ColumnLayout {
                            id: col
                            anchors.fill: parent; anchors.margins: 14
                            spacing: 10

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 10
                                Rectangle { width: 28; height: 28; radius: 14; color: card.a.color
                                    Text { anchors.centerIn: parent; text: card.a.name.charAt(0); color: "white"; font.bold: true } }
                                Text { text: card.a.name; color: Theme.text; font.pixelSize: Theme.fs(15); font.weight: Font.DemiBold }
                                Rectangle {
                                    radius: 6; implicitWidth: lbl.implicitWidth + 12; implicitHeight: 20
                                    color: card.a.found ? Qt.rgba(0.2, 0.83, 0.6, 0.15) : Qt.rgba(0.94, 0.27, 0.27, 0.15)
                                    Text { id: lbl; anchors.centerIn: parent; font.pixelSize: Theme.fs(10)
                                           text: card.a.found ? "bulundu" : "PATH'te yok"
                                           color: card.a.found ? "#3ddc84" : "#ef4444" }
                                }
                                Item { Layout.fillWidth: true }
                                Switch {
                                    checked: card.a.enabled
                                    onToggled: d.setAgent(card.index, "enabled", checked)
                                }
                            }

                            GridLayout {
                                columns: 2; columnSpacing: 12; rowSpacing: 8
                                Layout.fillWidth: true
                                Text { text: "Görünen ad"; color: Theme.textDim; font.pixelSize: Theme.fs(12) }
                                Field { Layout.fillWidth: true; text: card.a.name; onTextEdited: d.setAgent(card.index, "name", text) }
                                Text { text: "Komut"; color: Theme.textDim; font.pixelSize: Theme.fs(12) }
                                Field { Layout.fillWidth: true; text: card.a.command; font.family: "monospace"
                                        onTextEdited: d.setAgent(card.index, "command", text) }
                                Text { text: "Renk"; color: Theme.textDim; font.pixelSize: Theme.fs(12) }
                                RowLayout {
                                    spacing: 6
                                    Repeater {
                                        model: ["#4f8cff", "#d97757", "#10a37f", "#f59e0b", "#ec4899", "#06b6d4", "#eab308"]
                                        Rectangle {
                                            width: 22; height: 22; radius: 11; color: modelData
                                            border.color: card.a.color === modelData ? "white" : "transparent"; border.width: 2
                                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                                onClicked: { d.setAgent(card.index, "color", modelData) } }
                                        }
                                    }
                                }
                                Text { text: "Model"; color: Theme.textDim; font.pixelSize: Theme.fs(12) }
                                Picker {
                                    Layout.fillWidth: true
                                    value: card.a.model || ""
                                    items: d.models[card.a.key] ? d.models[card.a.key].models : []
                                    emptyLabel: d.models[card.a.key] ? "CLI varsayılanı" : "modeller yükleniyor…"
                                    onPicked: function(v) { d.setAgent(card.index, "model", v) }
                                }
                                Text { text: "Effort"; color: Theme.textDim; font.pixelSize: Theme.fs(12) }
                                RowLayout {
                                    spacing: 6
                                    Repeater {
                                        model: [""].concat(d.models[card.a.key] ? d.models[card.a.key].efforts
                                                                               : ["low", "medium", "high", "xhigh", "max"])
                                        Rectangle {
                                            readonly property bool sel: (card.a.effort || "") === modelData
                                            implicitWidth: et.implicitWidth + 16; implicitHeight: 28; radius: 8
                                            color: sel ? Qt.rgba(Qt.color(card.a.color).r, Qt.color(card.a.color).g, Qt.color(card.a.color).b, 0.25) : Theme.bg
                                            border.color: sel ? card.a.color : Theme.line
                                            Text { id: et; anchors.centerIn: parent; text: modelData || "varsayılan"
                                                   color: sel ? Theme.text : Theme.textDim; font.pixelSize: Theme.fs(11) }
                                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                                onClicked: { d.setAgent(card.index, "effort", modelData) } }
                                        }
                                    }
                                }
                                Text { visible: card.isAgy; Layout.alignment: Qt.AlignTop
                                       text: "Komutlar"; color: Theme.textDim; font.pixelSize: Theme.fs(12) }
                                Text {
                                    visible: card.isAgy
                                    Layout.fillWidth: true; wrapMode: Text.WordWrap
                                    color: Theme.muted; font.pixelSize: Theme.fs(11)
                                    text: "Üretimde --sandbox ile çalışır: proje klasörü ve /tmp dışına yazamaz, içinde her komutu çalıştırabilir (LifeosArch/ekip ile aynı). Tartışmada plan modundadır."
                                }
                                Text { text: "Zaman aşımı (sn)"; color: Theme.textDim; font.pixelSize: Theme.fs(12) }
                                Field { Layout.preferredWidth: 160; text: card.a.timeout ? String(card.a.timeout) : ""
                                        placeholderText: "sınırsız"; validator: IntValidator { bottom: 0 }
                                        onTextEdited: d.setAgent(card.index, "timeout", parseInt(text) || 0) }
                            }

                            Text {
                                Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: Theme.fs(11)
                                text: "{prompt} varsa döküm argüman olarak geçer, yoksa stdin'den verilir. Test, kaydedilmiş komutla \"Merhaba\" gönderir."
                            }

                            RowLayout {
                                spacing: 10
                                GhostButton {
                                    text: card.t && card.t.running ? "Test ediliyor…" : "Bağlantıyı test et"
                                    accent: card.a.color
                                    enabled: !(card.t && card.t.running)
                                    onClicked: {
                                        var x = Object.assign({}, d.tests); x[card.a.key] = { running: true }; d.tests = x
                                        room.test(card.a.key)
                                    }
                                }
                                Text {
                                    visible: !!card.t && !card.t.running
                                    text: card.t && card.t.ok ? "✓ yanıt verdi" : "✕ hata"
                                    color: card.t && card.t.ok ? "#3ddc84" : "#ef4444"; font.pixelSize: Theme.fs(12)
                                }
                            }
                            Rectangle {
                                visible: !!card.t && !card.t.running
                                Layout.fillWidth: true
                                implicitHeight: Math.min(outTxt.implicitHeight + 16, 140)
                                radius: 8; color: Theme.bg; clip: true
                                Text { id: outTxt; x: 8; y: 8; width: parent.width - 16; wrapMode: Text.WrapAnywhere
                                       text: card.t ? (card.t.out || "") : ""; color: Theme.textDim
                                       font.family: "monospace"; font.pixelSize: Theme.fs(11) }
                            }
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            GhostButton { text: "Varsayılana dön"; accent: "#ef4444"; onClicked: { room.resetSettings(); d.draft = JSON.parse(JSON.stringify(room.settings)) } }
            Item { Layout.fillWidth: true }
            GhostButton { text: "Vazgeç"; onClicked: d.close() }
            Button {
                id: save
                text: "Kaydet"
                implicitHeight: 34; implicitWidth: 100
                contentItem: Text { text: save.text; color: "white"; font.pixelSize: Theme.fs(13); font.bold: true
                                    horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                background: Rectangle { radius: 9; color: save.down ? Qt.darker(Theme.user, 1.2) : Theme.user }
                onClicked: { room.saveSettings(d.draft); d.close() }
            }
        }
    }
}
