"""
Chimera AI — Обучение нейросети Пророк на данных АПЛ (10 сезонов)
"""
import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'

import pandas as pd
import numpy as np
import glob
import json
import warnings
warnings.filterwarnings('ignore')

# --- 1. Загрузка данных ---
print("[1/5] Загружаю данные АПЛ...")
files = sorted(glob.glob('/home/ubuntu/chimera_ai_project/epl_data/*.csv'))
print(f"  Найдено файлов: {len(files)}")

dfs = []
for f in files:
    try:
        df = pd.read_csv(f, encoding='latin1', on_bad_lines='skip')
        dfs.append(df)
        print(f"  OK: {os.path.basename(f)} ({len(df)} строк)")
    except Exception as e:
        print(f"  SKIP: {f} — {e}")

if not dfs:
    print("ОШИБКА: нет файлов данных!")
    exit(1)

data = pd.concat(dfs, ignore_index=True)
print(f"  Итого: {len(data)} матчей")

# --- 2. Очистка ---
for col in ['HS','AS','HST','AST','HC','AC']:
    if col not in data.columns:
        data[col] = 0
    data[col] = pd.to_numeric(data[col], errors='coerce').fillna(0)

data = data[['HomeTeam','AwayTeam','FTHG','FTAG','FTR','HS','AS','HST','AST','HC','AC']].copy()
data = data.dropna(subset=['HomeTeam','AwayTeam','FTHG','FTAG','FTR'])
data = data[data['HomeTeam'].astype(str).str.strip().str.len() > 1]
data = data[data['FTR'].isin(['H','D','A'])].reset_index(drop=True)
print(f"  После очистки: {len(data)} матчей")

# --- 3. Кодирование команд ---
all_teams = sorted(set(data['HomeTeam'].unique()) | set(data['AwayTeam'].unique()))
team_to_id = {team: idx for idx, team in enumerate(all_teams)}
data['HomeTeam_encoded'] = data['HomeTeam'].map(team_to_id)
data['AwayTeam_encoded'] = data['AwayTeam'].map(team_to_id)
print(f"\n[2/5] Команды ({len(all_teams)}): {all_teams}")

# --- 4. Признаки ---
print("\n[3/5] Создаю признаки...")
for n in [5, 10]:
    data[f'H_avg_gs_{n}'] = data.groupby('HomeTeam')['FTHG'].transform(
        lambda x: x.shift(1).rolling(n, min_periods=1).mean()).fillna(1.3)
    data[f'H_avg_gc_{n}'] = data.groupby('HomeTeam')['FTAG'].transform(
        lambda x: x.shift(1).rolling(n, min_periods=1).mean()).fillna(1.3)
    data[f'A_avg_gs_{n}'] = data.groupby('AwayTeam')['FTAG'].transform(
        lambda x: x.shift(1).rolling(n, min_periods=1).mean()).fillna(1.1)
    data[f'A_avg_gc_{n}'] = data.groupby('AwayTeam')['FTHG'].transform(
        lambda x: x.shift(1).rolling(n, min_periods=1).mean()).fillna(1.1)

data['H_avg_shots_5'] = data.groupby('HomeTeam')['HS'].transform(
    lambda x: x.shift(1).rolling(5, min_periods=1).mean()).fillna(12)
data['A_avg_shots_5'] = data.groupby('AwayTeam')['AS'].transform(
    lambda x: x.shift(1).rolling(5, min_periods=1).mean()).fillna(10)
data['H_avg_sot_5'] = data.groupby('HomeTeam')['HST'].transform(
    lambda x: x.shift(1).rolling(5, min_periods=1).mean()).fillna(4)
data['A_avg_sot_5'] = data.groupby('AwayTeam')['AST'].transform(
    lambda x: x.shift(1).rolling(5, min_periods=1).mean()).fillna(3.5)
data['H_avg_corners_5'] = data.groupby('HomeTeam')['HC'].transform(
    lambda x: x.shift(1).rolling(5, min_periods=1).mean()).fillna(5)
data['A_avg_corners_5'] = data.groupby('AwayTeam')['AC'].transform(
    lambda x: x.shift(1).rolling(5, min_periods=1).mean()).fillna(4.5)
data['H_goal_diff'] = data['H_avg_gs_5'] - data['H_avg_gc_5']
data['A_goal_diff'] = data['A_avg_gs_5'] - data['A_avg_gc_5']
data['strength_diff'] = data['H_avg_gs_5'] - data['A_avg_gs_5']

feature_cols = [
    'HomeTeam_encoded', 'AwayTeam_encoded',
    'H_avg_gs_5', 'H_avg_gc_5', 'H_avg_gs_10', 'H_avg_gc_10',
    'A_avg_gs_5', 'A_avg_gc_5', 'A_avg_gs_10', 'A_avg_gc_10',
    'H_avg_shots_5', 'A_avg_shots_5', 'H_avg_sot_5', 'A_avg_sot_5',
    'H_avg_corners_5', 'A_avg_corners_5',
    'H_goal_diff', 'A_goal_diff', 'strength_diff'
]

label_map = {'D': 0, 'H': 1, 'A': 2}
data['label'] = data['FTR'].map(label_map)
clean = data[feature_cols + ['label', 'HomeTeam', 'AwayTeam']].dropna()
print(f"  Чистых матчей: {len(clean)}")
print(f"  Исходы: {clean['label'].value_counts().to_dict()}")

# Сохраняем датасет
clean.to_csv('/home/ubuntu/chimera_ai_project/all_matches_featured.csv')
print("  ✅ all_matches_featured.csv сохранён")

with open('/home/ubuntu/chimera_ai_project/team_encoder.json', 'w', encoding='utf-8') as f:
    json.dump(team_to_id, f, ensure_ascii=False, indent=2)
print("  ✅ team_encoder.json сохранён")

# --- 5. Обучение ---
print("\n[4/5] Подготавливаю данные для LSTM...")
from sklearn.preprocessing import MinMaxScaler
from sklearn.model_selection import train_test_split

X = clean[feature_cols].values
y = clean['label'].values

scaler = MinMaxScaler()
X_scaled = scaler.fit_transform(X)

SEQ_LEN = 10
X_seq, y_seq = [], []
for i in range(SEQ_LEN, len(X_scaled)):
    X_seq.append(X_scaled[i-SEQ_LEN:i])
    y_seq.append(y[i])

X_seq = np.array(X_seq)
y_seq = np.array(y_seq)
print(f"  Последовательностей: {len(X_seq)}, форма: {X_seq.shape}")

X_train, X_test, y_train, y_test = train_test_split(X_seq, y_seq, test_size=0.15, random_state=42)

print("\n[5/5] Обучаю нейросеть...")
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout, BatchNormalization
from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau

model = Sequential([
    LSTM(128, return_sequences=True, input_shape=(SEQ_LEN, len(feature_cols))),
    BatchNormalization(),
    Dropout(0.3),
    LSTM(64, return_sequences=False),
    BatchNormalization(),
    Dropout(0.3),
    Dense(32, activation='relu'),
    Dropout(0.2),
    Dense(3, activation='softmax')
])

model.compile(
    optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
    loss='sparse_categorical_crossentropy',
    metrics=['accuracy']
)

callbacks = [
    EarlyStopping(monitor='val_accuracy', patience=8, restore_best_weights=True, verbose=1),
    ReduceLROnPlateau(monitor='val_loss', factor=0.5, patience=4, min_lr=0.0001, verbose=1)
]

history = model.fit(
    X_train, y_train,
    epochs=50,
    batch_size=32,
    validation_data=(X_test, y_test),
    callbacks=callbacks,
    verbose=1
)

test_loss, test_acc = model.evaluate(X_test, y_test, verbose=0)
print(f"\n✅ Точность на тестовых данных: {test_acc*100:.1f}%")

model.save('/home/ubuntu/chimera_ai_project/prophet_model.keras')
print("✅ Модель сохранена: prophet_model.keras")
print("\n🎉 Готово! Пророк обучен на данных АПЛ.")
