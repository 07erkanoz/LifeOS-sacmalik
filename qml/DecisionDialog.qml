import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Karar penceresi, üç iş için:
//   open   — karar aç: herkes ilk görüşünü ötekilerinkini görmeden yazar, cevaplar hepsi bitince birlikte açılır
//   record — alınan kararı tek cümleyle yaz (odaya sabitlenir, ajanlara oda bilgisiyle gider)
//   prod   — Üretim'i açarken hangi kararın uygulandığını yaz (boş bırakılabilir)
Popup {
    id: d
    modal: true
    anchors.centerIn: Overlay.overlay
    width: Math.min(600, win.width - 80)
    height: Math.min(col.implicitHeight + 44, win.height - 80)
    padding: 22
    property string mode: "open"
    function show(m) { mode = m; open() }
    onAboutToShow: {
        var dc = room.decision
        txt.text = mode === "prod" ? (dc.last || "") : ""
        txt.forceActiveFocus()
    }
    function accept() {
        var t = txt.text.trim()
        if (mode === "open") { if (!t) return; if (room.openDecision(t)) d.close() }
        else if (mode === "record") { if (!t) return; room.recordDecision(t); d.close() }
        else { room.startProduction(t); d.close() }
    }
    enter: Transition { ParallelAnimation {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 160 }
        NumberAnimation { property: "scale"; from: 0.97; to: 1; duration: 200; easing.type: Easing.OutCubic } } }
    background: Rectangle { radius: 16; color: Theme.panel; border.color: Theme.line }
    Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.45) }

    contentItem: ColumnLayout {
        id: col
        spacing: 12
        Text {
            text: d.mode === "open" ? "🗳 Karar aç" : d.mode === "record" ? "✅ Kararı yaz" : "🛠 Üretimi aç"
            color: Theme.text; font.pixelSize: Theme.fs(18); font.weight: Font.Bold
        }
        Text {
            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: Theme.fs(12)
            text: d.mode === "open"
                ? "Yanlış seçilirse çok iş tekrarı çıkaracak kararlar için. Sözü açık her ajan ilk görüşünü "
                  + "ötekilerin cevabını görmeden yazar; cevaplar hepsi bitince birlikte açılır, sonra sohbet "
                  + "serbestçe sürer. Ajanlara iki şey sorulur: önce hangi yolu denerdin, hangi bulgu fikrini değiştirirdi."
                : d.mode === "record"
                ? "Alınan kararı tek cümleyle yaz. Odaya sabitlenir; ajanlar onu oda bilgisiyle alır, döküm kırpılsa da unutmaz."
                : "Üretimde hangi karar uygulanacak? Tek cümle yeter; odaya yazılır ve üretim boyunca ajanlara gider. "
                  + "Boş bırakırsan yalnız mod değişir."
        }
        Field {
            id: txt
            Layout.fillWidth: true
            implicitHeight: 40
            placeholderText: d.mode === "open" ? "Örnek: İlk çalışan haritayı hazır katmanlarla mı, kendi çizimimizle mi kuracağız?"
                           : d.mode === "record" ? "Örnek: Önce Alanya'nın küçük bir kesimini hazır katmanlarla deneyip telefonda ölçeceğiz."
                           : "Örnek: Hazır katmanlarla ilk iskelet; çevrimdışı çizim kararı açık."
            onAccepted: d.accept()
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Item { Layout.fillWidth: true }
            GhostButton { text: "Vazgeç"; onClicked: d.close() }
            Button {
                id: ok
                text: d.mode === "open" ? "Kararı aç" : d.mode === "record" ? "Kaydet" : "Üretimi aç"
                enabled: d.mode === "prod" || txt.text.trim().length > 0
                opacity: enabled ? 1 : 0.5
                implicitHeight: 34
                contentItem: Text { text: ok.text; color: "white"; font.pixelSize: Theme.fs(13); font.bold: true
                                    horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                                    leftPadding: 10; rightPadding: 10 }
                background: Rectangle { radius: 9; color: d.mode === "prod" ? "#9a3412" : ok.down ? Theme.userHi : Theme.user }
                onClicked: d.accept()
            }
        }
    }
}
