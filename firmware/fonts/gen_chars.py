# 生成 LVGL 中文字体（GB2312 全量 7446 字）的脚本
# 用法（PowerShell）：
#   npm install -g lv_font_conv
#   python gen_chars.py            # 生成 chars_gb2312.txt
#   然后按下方 lv_font_conv 命令生成字体，输出到 main/lv_font_simhei_16.c
#
# 说明：
#   - 源字体：Windows 自带黑体 C:\Windows\Fonts\simhei.ttf（GB2312 字符集）
#   - 字符集：GB2312 全部汉字（6763）+ 中文标点/符号（约 680）+ 常用补充字符
#   - 参数：16px、bpp4（抗锯齿）、ASCII 0x20-0x7F + 自定义符号表
#   - 覆盖日常对话 99.9% 中文文本，替代 LVGL 内置 1338 字 CJK 字体（大量缺字）

chars = set()
# GB2312 全部双字节字符（区 01-09 符号 + 区 16-87 汉字），自动跳过未定义空位
for b1 in range(0xA1, 0xF8):
    for b2 in range(0xA1, 0xFF):
        try:
            ch = bytes([b1, b2]).decode('gb2312')
            if ch and not ch.isspace():
                chars.add(ch)
        except UnicodeDecodeError:
            pass
# 额外补充 GB2312 没有但常用的字符
chars.update('…—·～℃°“”‘’①②③④⑤⑥⑦⑧⑨⑩')
s = ''.join(sorted(chars))
with open('chars_gb2312.txt', 'w', encoding='utf-8') as f:
    f.write(s)
print('total chars:', len(s))
