import csv
import math
import argparse
import sys
import os
import datetime

def parse_csv(csv_path):
	"""讀取並解析 CtrlCode.csv，回傳 1-bit 序列資料流與總位元數"""
	bitstream = []
	
	if not os.path.exists(csv_path):
		raise FileNotFoundError(f"找不到指定的輸入檔案: {csv_path}")

	# 使用 utf-8-sig 自動處理可能帶有 BOM 的 CSV 檔案
	with open(csv_path, mode='r', encoding='utf-8-sig') as f:
		reader = csv.DictReader(f)
		
		# 驗證 CSV 標頭是否正確
		required_fields = ['Data Name', 'Bit Width', 'Direction', 'Value']
		if not all(field in reader.fieldnames for field in required_fields):
			raise KeyError(f"CSV 標頭缺失或格式錯誤。必須包含: {', '.join(required_fields)}")

		for line_idx, row in enumerate(reader, start=2):
			try:
				name = row.get('Data Name', f'Row_{line_idx}')
				bit_count = int(row['Bit Width'])
				direction = int(row['Direction'])
				value = int(row['Value'])
			except ValueError as e:
				raise ValueError(f"第 {line_idx} 行資料解析失敗 (請確認數值皆為整數): {e}")

			# 異常處理：檢查數值是否為負數，或是否超過位元數能表示的最大值
			if value < 0:
				raise ValueError(f"數值錯誤: 第 {line_idx} 行 ({name}) 數值不能為負數 ({value})。")
			if value >= (1 << bit_count):
				raise ValueError(f"溢位錯誤: 第 {line_idx} 行 ({name}) 的數值 {value} 超出 {bit_count} bits 可表示的範圍。")

			# 轉換為指定位元數長度的二進位字串 (補零)
			bin_str = format(value, f'0{bit_count}b')
			
			if direction == 1:
				bits = [int(b) for b in bin_str]			# start output from MSB
			elif direction == 0:
				bits = [int(b) for b in reversed(bin_str)]	# start output from LSB
			else:
				raise ValueError(f"方向值錯誤: 第 {line_idx} 行 ({name}) 的方向為 {direction}，僅接受 0 或 1。")

			bitstream.extend(bits)

	return bitstream, len(bitstream)
	

def format_row(addr_index, pg_func=0x000, data=0, clk_m=0, clk_s=0, addr=0, scan_in=0, en_scan_in=0, rst_ckt=0, rst_cnt=0, en_scan_out=0):
	"""將參數格式化為固定寬度並對齊，行尾附上從 0 開始的十六進位位址註解"""
	part1 = f"{pg_func:03X}h"
	part2 = f"{clk_m} {clk_s} {addr:>4} {scan_in} {en_scan_in} {rst_ckt} {rst_cnt} {en_scan_out} {1 - en_scan_out}"
	
	# 利用固定寬度讓文字對齊，並確保每行附加上對齊的 16 進位行號註解
	line = f"{part1:<6} {part2:<20}"
	return f"{line:<26} // {addr_index:04X}h {addr_index:04}"

def write_headers(f, total_bits, addr_index):
	"""寫入 No Time Stamp 模式的標頭與腳位映射 (ASSIGN)"""
	N = 0 if total_bits <= 1 else math.ceil(math.log2(total_bits)) - 1
	f.write(f"INPUTS PG_Function CLK_M CLK_S addr scan_in EN_SCAN_IN RST_CKT RST_CNT EN_SCAN_OUT ENb_SCAN_OUT;\n")
	f.write(f"ASSIGN addr 0..{N};\n")
	f.write(f"ASSIGN CLK_M {N+1};\n")
	f.write(f"ASSIGN CLK_S {N+2};\n")
	f.write(f"ASSIGN scan_in {N+3};\n")
	f.write(f"ASSIGN EN_SCAN_IN {N+4};\n")
	f.write(f"ASSIGN RST_CKT {N+5};\n")
	f.write(f"ASSIGN RST_CNT {N+6};\n")
	f.write(f"ASSIGN EN_SCAN_OUT {N+7};\n")
	f.write(f"ASSIGN ENb_SCAN_OUT {N+8};\n")
	f.write("RADIX AUTO;\n")
	f.write("FREQUENCYMODE INTERNAL;\n")
	f.write("FREQUENCY 1 MHz;\n")
	f.write("PATTERN\n")

	for _ in range(10):
		f.write(format_row(addr_index) + '\n')
		addr_index += 1
	
	f.write(format_row(addr_index, pg_func=0x8FF) + ' (MOV RL, 255)\n')
	addr_index += 1
	f.write(format_row(addr_index, pg_func=0x2FF) + ' (MOV RH, 255)\n')
	addr_index += 1
	f.write(format_row(addr_index, pg_func=0x900) + ' OE 65535     \n')
	addr_index += 1

	return addr_index

def do_reset(f, addr_index):
	"""RESET 階段：持續 20us (20 列)"""
	for _ in range(10):
		f.write(format_row(addr_index) + '\n')
		addr_index += 1
	for _ in range(20):
		f.write(format_row(addr_index, rst_ckt=1, rst_cnt=1) + '\n')
		addr_index += 1
	for _ in range(10):
		f.write(format_row(addr_index) + '\n')
		addr_index += 1
	
	return addr_index

def do_write(f, addr_index, bitstream):
	"""WRITE 階段：將 bitstream 寫入目標晶片"""
	total_bits = len(bitstream)
	for bit_idx in range(total_bits):
		scan_val = bitstream[bit_idx]
		# 每個 bit 傳輸週期為 10us (10 列)
		for row in range(10):
			clk_m = 1 if 3 <= row <= 6 else 0
			if bit_idx == 0:
				clk_s = 1 if row in (8, 9) else 0
			else:
				clk_s = 1 if row in (0, 1, 8, 9) else 0
			f.write(format_row(
				addr_index, 
				clk_m=clk_m, 
				clk_s=clk_s, 
				addr=bit_idx, 
				scan_in=scan_val,
				en_scan_in=1
			) + '\n')
			addr_index += 1

	f.write(format_row(addr_index, clk_m=0, clk_s=1, en_scan_in=1) + '\n')
	addr_index += 1
	f.write(format_row(addr_index, clk_m=0, clk_s=1, en_scan_in=1) + '\n')
	addr_index += 1

	# Latch 鎖存階段：EN_SCAN_IN 拉至 0，並發送一組完整的 CLK
	for row in range(30):
		clk_m = 1 if 13 <= row <= 16 else 0
		clk_s = 1 if 18 <= row <= 21 else 0
		f.write(format_row(addr_index, clk_m=clk_m, clk_s=clk_s, en_scan_in=0) + ' Load into circuit\n')
		addr_index += 1

	return addr_index

def do_reset_cnt(f, addr_index):
	for _ in range(10):
			f.write(format_row(addr_index) + '\n')
			addr_index += 1
	
	# reset counter
	for _ in range(10):
		f.write(format_row(addr_index, rst_ckt=0, rst_cnt=1) + '\n')
		addr_index += 1
		
	# 收尾：將所有訊號歸零
	for _ in range(5):
		f.write(format_row(addr_index) + '\n')
		addr_index += 1
	
	return addr_index

def do_wait(f, addr_index, wait_cycles, unit):
	"""
	WAIT 階段：利用 PG 內建 LOOP 功能空轉等待。
	傳入之 wait_cycles 為目標等待時間，單位為 256 cycles。
	"""
	if wait_cycles < 2:
		print("[!] Warning: PG 暫存器限制 LC 最小值為 2。已自動將等待參數修正為 2。")
		wait_cycles = 2
	elif wait_cycles > 65536:
		print("[!] Warning: PG 暫存器限制 LC 最大值為 65536。已自動將等待參數修正為 65536。")
		wait_cycles = 65536

	if unit < 4:
		print("[!] Warning: unit too small, and is reset to 4")
		unit = 4
	elif unit > 50000:
		unit = 50000
		print("[!] Warning: unit too large, and is reset to 50000")

	print(f"[*] Waiting time: \t{wait_cycles} x {unit} us = {wait_cycles*unit/1000000} s")
	
	# 1. 寫入 LC 暫存器 (設定迴圈次數)
	f.write(format_row(addr_index, pg_func=0x800 + (wait_cycles & 0xFF)) + ' LC: RL \n')           # MOV RL, LSB
	addr_index += 1
	f.write(format_row(addr_index, pg_func=0x200 + ((wait_cycles >> 8) & 0xFF)) + ' LC: RH\n')    # MOV RH, MSB
	addr_index += 1
	f.write(format_row(addr_index, pg_func=0x400) + f" LC: {wait_cycles} cycles \n")                                  # MOV LC, 從 RL/RH 載入
	addr_index += 1
	
	# 紀錄 Loop 的起始位址
	loop_start_addr = addr_index + 12
	
	# 2. 迴圈本體 (單位為 250 cycles，因此迴圈總共要經過 250 列)
	# 跳轉設定需要占用 3 列 (MOV RL, MOV RH, LP)，因此空轉 IDLE 需 247 列
	for _ in range(unit - 3):
		f.write(format_row(addr_index) + '\n')
		addr_index += 1
		
	# 3. 執行 LP 條件跳轉 (跳回 loop_start_addr)
	f.write(format_row(addr_index, pg_func=0x800 + (loop_start_addr & 0xFF)) + ' LP: RL \n')        # MOV RL
	addr_index += 1
	f.write(format_row(addr_index, pg_func=0x200 + ((loop_start_addr >> 8) & 0xFF)) + ' LP: RH \n') # MOV RH
	addr_index += 1
	f.write(format_row(addr_index, pg_func=0x300) + f" LP: {loop_start_addr:04X}h\n")                                   # LP 執行跳轉並將 LC-1
	addr_index += 1
	
	return addr_index

def do_read(f, addr_index):
	"""READ 階段：發送等量時脈週期但不 scan-in，用以將資料移出或驗證"""

	for j in range(15):
		clk_m_val = 1 if 3 <= j <= 6 else 0
		clk_s_val = 1 if 8 <= j <= 11 else 0
		f.write(format_row(addr_index, clk_m=clk_m_val, clk_s=clk_s_val) + '\n')
		addr_index += 1

	for data_idx in range(4):
		for bit_idx in range(40):
			for row in range(10):
				# clk_m = 1 if 3 <= row <= 6 else 0
				if data_idx == 0 and bit_idx == 0:
					clk_m = 0
					clk_s = 1 if row in (8, 9) else 0
				else:
					clk_m = 1 if row in (3, 4, 5, 6) else 0
					clk_s = 1 if row in (0, 1, 8, 9) else 0
				addr = 9 - ((bit_idx) // 4) 
				f.write(format_row(addr_index, clk_m=clk_m, clk_s=clk_s, addr=addr, en_scan_out=1) + '\n')
				addr_index += 1

	for j in range(15):
		clk_m_val = 1 if j in (3, 4, 5, 6) else 0
		clk_s_val = 1 if j in (0, 1, 8, 9, 10, 11) else 0
		f.write(format_row(addr_index, clk_m=clk_m_val, clk_s=clk_s_val,  en_scan_out=1) + '\n')
		addr_index += 1
	
	# 收尾歸零
	f.write(format_row(addr_index) + '\n')
	addr_index += 1
	return addr_index

def do_jump(f, addr_index, jump_addr):
	""" 啟用重複執行 """
	print(f"[*] Jump back to: \t{jump_addr:d}d ({jump_addr:04X}h)")
	f.write(format_row(addr_index, pg_func=0x800 + (jump_addr & 0xFF)) + ' JP: RL \n')        # MOV RL
	addr_index += 1
	f.write(format_row(addr_index, pg_func=0x200 + ((jump_addr >> 8) & 0xFF)) + ' JP: RH \n') # MOV RH
	addr_index += 1
	f.write(format_row(addr_index, pg_func=0x100) + f" JP: {jump_addr:04X}h\n")                                   # LP 執行跳轉並將 LC-1
	addr_index += 1

def main():
	parser = argparse.ArgumentParser(description="Acute PGV Vector Generator (自動轉換 CSV 為 PGV)")
	parser.add_argument('-i', '--input', default='CtrlCode.csv', help="輸入的 CSV 檔案路徑 (預設: CtrlCode.csv)")
	parser.add_argument('-o', '--output', default='output.pgv', help="輸出的 PGV 檔案路徑 (預設: output.pgv)")
	
	# 階段控制指令
	parser.add_argument('-RST', '--reset', action='store_true', help="包含 RESET 初始階段")
	parser.add_argument('-W', '--write', action='store_true', help="包含 WRITE 資料掃入階段")
	parser.add_argument('-R', '--read', action='store_true', help="包含 READ 資料讀出階段")
	parser.add_argument('-t', '--wait', type=int, default=1000, help="設定 WRITE 後的等待時間 [例如 -t 10000 (單位 -unit)]")
	parser.add_argument('-u', '--unit', type=int, default=10000, help="設定 WAIT 時間單位，例如：-t 1000 -u 1000 代表延遲 1 sec")
	parser.add_argument('-j', '--jump', action='store_true', help="跳到 WAIT 迴圈前，執行重複掃描")
	
	args = parser.parse_args()

	# 讀取 CSV
	try:
		print(f"[*] Analyzing: \t\t{args.input} ...")
		bitstream, total_bits = parse_csv(args.input)
		print(f"[*] Finish analyzing: \tobtain {total_bits}-bit sequential data.")

	except Exception as e:
		print(f"[x] ERROR: {e}, Fail to interpret CSV file")
		sys.exit(1)

	# 統一先清空目標檔案，再依序將使用者指定的指令寫入
	with open(args.output, 'w', encoding='utf-8') as f:
		# 維護一個全域的位址索引
		addr_index = 0
		jump_addr = 0

		addr_index = write_headers(f, total_bits, addr_index)
		
		if args.reset:
			addr_index = do_reset(f, addr_index)
			
		if args.write:
			addr_index = do_write(f, addr_index, bitstream)

		addr_index = do_reset_cnt(f, addr_index)
		
		if args.write and args.read:
			jump_addr = addr_index
			addr_index = do_wait(f, addr_index, args.wait, args.unit)
		if args.read:
			addr_index = do_read(f, addr_index)
		if args.jump and args.write and args.read:
			addr_index = do_jump(f, addr_index, jump_addr + 10)

		# Allow quick BER result accquiring before repeating read-out
		# if args.read:
		# 	addr_index = do_wait(f, addr_index, wait_cycles=400, unit=250)
		# 	jump_addr = addr_index
		# 	addr_index = do_read(f, addr_index)
		# if args.write and args.read:
		# 	addr_index = do_wait(f, addr_index, args.wait, args.unit)
		# if args.jump and args.write and args.read:
		# 	for _ in range(10):
		# 		f.write(format_row(addr_index) + '\n')
		# 		addr_index += 1
		# 	addr_index = do_jump(f, addr_index, jump_addr + 10)
		
	print(f"[v] PGV file generated: {args.output}")
	print(f"[*] Job done time: \t{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
	main()