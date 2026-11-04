# LOTRO Türkçe Yama

**[Türkçe](#türkçe)**&nbsp;&nbsp;&nbsp;&nbsp;**[English](#english)**

## Türkçe

The Lord of the Rings Online için gayriresmî Türkçe çeviri. Menüler, beceriler, eşyalar, görevler ve diyaloglar dahil oyundaki 525 binden fazla metin Türkçeye çevrildi.

### Kurulum

1. **[LOTRO-Turkce.zip](https://github.com/NeuralFoundry/lotro-turkish-translation/releases/latest/download/LOTRO-Turkce.zip)** dosyasını indirin.
2. İndirdiğiniz dosyaya sağ tıklayın ve **Tümünü ayıkla** deyin.
3. Oyunu ve başlatıcıyı kapatın.
4. Açılan klasördeki **Kur.cmd** dosyasına çift tıklayın. Windows izin isterse **Evet** deyin.
5. **Kurulum tamamlandı** yazısını görünce oyunu her zamanki gibi başlatın.

Kurulum yaklaşık bir dakika sürer. Oyunun klasörü otomatik olarak bulunur. Bulunamazsa klasörü açılan pencereye sürükleyip Enter'a basmanız istenir.

### Kaldırma

Oyunu kapatın ve **Kaldir.cmd** dosyasına çift tıklayın. Oyun dosyası kurulumdan önceki haline birebir döner.

### Oyun güncellemesinden sonra

Bir güncelleme bazı yazıları yeniden İngilizce yapabilir. Oyunu kapatıp **Kur.cmd** dosyasını tekrar çalıştırmanız yeterlidir.

### Gereksinimler

* Windows 10 veya Windows 11
* Oyun dilinin **English** olması
* Oyunun bulunduğu sürücüde yaklaşık 350 MB boş alan

**Python kurmanıza gerek yok.** Gerekli Python paketin içinde gelir. Başka bir program da gerekmez.

### Sık sorulan sorular

**Windows bir güvenlik uyarısı gösterdi.**
İnternetten indirilen dosyalarda bu uyarı normaldir. **Ek bilgi** ve ardından **Yine de çalıştır** seçeneğine, ya da doğrudan **Çalıştır** düğmesine tıklayın.

**"Oyun ya da başlatıcı açık" uyarısı alıyorum.**
Oyunu ve başlatıcıyı tamamen kapatın, ardından Kur.cmd dosyasını yeniden çalıştırın.

**Yer adları neden İngilizce?**
Yer, kitap ve bölüm adları bilerek orijinal halleriyle bırakıldı. Böylece haritalarda, rehberlerde ve diğer oyuncularla aynı adları kullanırsınız.

**Çeviride bir hata buldum.**
[Issues](https://github.com/NeuralFoundry/lotro-turkish-translation/issues) bölümünden ekran görüntüsüyle bildirebilirsiniz.

### Bilinen sorunlar

* Küçük büyük harflerle yazılan bazı başlıklarda "İ" harfi noktasız görünür.

### Yasal uyarı

Bu proje gayriresmî bir hayran çalışmasıdır. Standing Stone Games, Daybreak Game Company veya Middle-earth Enterprises ile bir bağlantısı yoktur. The Lord of the Rings Online ve ilgili adlar sahiplerinin ticari markalarıdır. Bu depoda oyunun orijinal metinleri bulunmaz. Yama, oyunun bilgisayarınızdaki dil dosyasını değiştirir. Kullanım sorumluluğu size aittir.

## English

An unofficial Turkish translation of The Lord of the Rings Online. More than 525,000 strings are translated, including menus, skills, items, quests and dialogue.

### Install

1. Download **[LOTRO-Turkce.zip](https://github.com/NeuralFoundry/lotro-turkish-translation/releases/latest/download/LOTRO-Turkce.zip)**.
2. Right-click the downloaded file and choose **Extract All**.
3. Close the game and the launcher.
4. In the extracted folder, double-click **Kur.cmd** (install). Choose **Yes** if Windows asks for permission.
5. When the window says **Kurulum tamamlandı** (installation complete), start the game as usual.

The game folder is found automatically. If it is not, drag the game folder into the window and press Enter.

### Uninstall

Close the game and double-click **Kaldir.cmd** (uninstall). The game file returns to exactly what it was before installation.

### After a game update

An update can turn some text back to English. Close the game and run **Kur.cmd** again.

### Requirements

* Windows 10 or Windows 11
* Game language set to **English**
* About 350 MB of free space on the game's drive

**You do not need to install Python.** It comes inside the package. Nothing else needs to be installed.

### How it works

Only `client_local_English.dat` is changed. The translated text tables are appended to the end of the file and the file header is pointed at them, so no original byte is overwritten. Uninstalling restores the original header and removes the appended data. Each step is verified with a SHA-256 of the whole file, and an interrupted install is undone on the next run. Translations are stored by a hash of the English text, so this repository contains no game text.

### For developers

* `app/lotro_tr.py`: the installer (`install`, `uninstall`, `status`, `check`, `find`). `--game <folder>` skips the search.
* `translations/*.tsv`: one `key<TAB>turkish` line per string. The key is the first 8 bytes of a BLAKE2b hash of the English text, as UTF-8.
* `tools/make_translations.py`: builds the translation files from `english<TAB>turkish` files.
* `tools/build_release.py`: builds the release ZIP with the official embedded Python.

Requires Python 3.8 or newer on Windows, with no third-party packages.

### License

The code is released under the [MIT License](LICENSE). The translations are a non-commercial fan work. The Lord of the Rings Online and related names are trademarks of their respective owners. This project is not affiliated with Standing Stone Games, Daybreak Game Company or Middle-earth Enterprises.
