import json
import os
from datetime import datetime, timedelta

import csv
import matplotlib.pyplot as plt
from matplotlib.cm import get_cmap
from kivy.utils import platform
from kivy.app import App
from kivy.lang import Builder
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.core.window import Window
from kivy.uix.popup import Popup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy_garden.matplotlib.backend_kivyagg import FigureCanvasKivyAgg
from kivy.animation import Animation
from kivy.properties import StringProperty

# Window.size = (600, 800)

DATA_FILE = "data.json"

def get_rainbow_colour(index, total, alpha=0.3):
    """Return a gentle transparent colour from the rainbow colormap."""
    cmap = get_cmap("rainbow")
    r, g, b, _ = cmap(index / max(1, total - 1))
    return [r, g, b, alpha]

class HomeScreen(Screen):
    pass

class DataEntryScreen(Screen):
    def open_input_screen(self, section_tag):
        input_screen = self.manager.get_screen("input_screen")
        input_screen.selected_section = section_tag
        input_screen.ids.section_label.text = f"Enter measurement for {section_tag}"
        input_screen.entered_value = ""
        input_screen.ids.display_value.text = ""
        input_screen.ids.status_label.text = ""
        self.manager.current = "input_screen"

class MeasurementInputScreen(Screen):
    selected_section = StringProperty("")
    entered_value = StringProperty("")

    def append_number(self, char):
        if len(self.entered_value) < 4:
            self.entered_value += char
            self.ids.display_value.text = self.entered_value

    def delete_last(self):
        self.entered_value = self.entered_value[:-1]
        self.ids.display_value.text = self.entered_value

    def round_to_next_hour(self, dt):
        return (dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))

    def save_measurement(self):
        if not self.entered_value.strip():
            return True

        try:
            value = float(self.entered_value)
            if not (0 <= value <= 10):
                raise ValueError
        except ValueError:
            if 'status_label' in self.ids:
                self.ids.status_label.text = "Please enter a number between 0 and 10"
            return False

        rounded_timestamp = self.round_to_next_hour(datetime.now())
        timestamp_str = rounded_timestamp.strftime("%Y-%m-%d %H:%M:%S")
        entry = {"value": value, "timestamp": timestamp_str}

        data = self.load_data()

        # Check existing data for this section and hour
        section_entries = data.get(self.selected_section, [])
        for existing_entry in section_entries:
            if existing_entry["timestamp"] == timestamp_str:
                if existing_entry["value"] < value:
                    existing_entry["value"] = value
                break
        else:
            section_entries.append(entry)

        data[self.selected_section] = section_entries
        self.write_data(data)

        self.entered_value = ""
        if 'display_value' in self.ids:
            self.ids.display_value.text = ""

        return True

    def save_and_return(self):
        if self.save_measurement():
            self.manager.current = "data_entry"

    @staticmethod
    def load_data():
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        return {}

    @staticmethod
    def write_data(data):
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)

class MeasurementApp(App):
    def build(self):
        Builder.load_file("main.kv")
        sm = ScreenManager()
        sm.add_widget(HomeScreen(name="home"))
        sm.add_widget(DataEntryScreen(name="data_entry"))
        sm.add_widget(MeasurementInputScreen(name="input_screen"))
        sm.add_widget(ViewDataScreen(name="view_data"))
        sm.add_widget(PlotScreen(name="plot_screen"))
        sm.add_widget(StatsScreen(name="stats_screen"))
        sm.add_widget(SleepInputScreen(name="sleep_input"))

        return sm

    @staticmethod
    def get_rainbow_colour(index, total):
        return get_rainbow_colour(index, total)

    @staticmethod
    def animate_button(button):
        anim = Animation(scale=1.1, duration=0.05) + Animation(scale=1.0, duration=0.05)
        anim.start(button)

    @staticmethod
    def export_csv():
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
        else:
            print("No data to export.")
            return

        if platform == "android":
            from android.storage import primary_external_storage_path
            export_dir = primary_external_storage_path() + "/Download"
        else:
            export_dir = os.path.expanduser("~/Downloads")

        os.makedirs(export_dir, exist_ok=True)
        csv_path = os.path.join(export_dir, "pain_management.csv")

        with open(csv_path, "w", newline="") as csvfile:
            writer = csv.writer(csvfile)

            # Write pain data
            writer.writerow(["section", "value", "timestamp"])
            for section, entries in data.items():
                if section != "sleep_data":
                    for entry in entries:
                        writer.writerow([section, entry["value"], entry["timestamp"]])

            # Write sleep data separately
            if "sleep_data" in data:
                writer.writerow([])
                writer.writerow(["Sleep Data"])
                writer.writerow(["date", "hours_slept", "sleep_quality"])
                for entry in data["sleep_data"]:
                    writer.writerow([entry["date"], entry["hours_slept"], entry["sleep_quality"]])

        print(f"Data exported to: {csv_path}")

        # Android email sharing code remains the same
        if platform == "android":
            from jnius import autoclass, cast
            from android.storage import primary_external_storage_path

            Context = autoclass("android.content.Context")
            Intent = autoclass("android.content.Intent")
            File = autoclass("java.io.File")
            FileProvider = autoclass("androidx.core.content.FileProvider")
            Uri = autoclass("android.net.Uri")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")

            currentActivity = PythonActivity.mActivity
            context = cast("android.content.Context", currentActivity)

            file_obj = File(csv_path)
            uri = FileProvider.getUriForFile(
                context,
                context.getPackageName() + ".fileprovider",
                file_obj
            )

            intent = Intent(Intent.ACTION_SEND)
            intent.setType("text/csv")
            intent.putExtra(Intent.EXTRA_SUBJECT, "Pain and Sleep Data")
            intent.putExtra(Intent.EXTRA_TEXT, "Attached is the exported CSV data.")
            intent.putExtra(Intent.EXTRA_STREAM, cast("android.os.Parcelable", uri))
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)

            chooser = Intent.createChooser(intent, "Send CSV via...")
            currentActivity.startActivity(chooser)

    def show_delete_confirmation(self):
        layout = BoxLayout(orientation='vertical', padding=20, spacing=10)
        message = Label(text="Are you sure?")
        layout.add_widget(message)

        buttons = BoxLayout(spacing=10, size_hint_y=None, height="48dp")
        cancel_btn = Button(text="Cancel")
        confirm_btn = Button(text="Yes, Delete", background_color=(0.8, 0.1, 0.1, 1))

        popup = Popup(title="Confirm Delete", content=layout,
                      size_hint=(None, None), size=("300dp", "200dp"),
                      auto_dismiss=False)

        cancel_btn.bind(on_press=popup.dismiss)
        confirm_btn.bind(on_press=lambda *a: self.delete_data(popup))

        buttons.add_widget(cancel_btn)
        buttons.add_widget(confirm_btn)
        layout.add_widget(buttons)
        popup.open()

    def delete_data(self, popup):
        if os.path.exists(DATA_FILE):
            os.remove(DATA_FILE)
            print("Data deleted.")
        else:
            print("No data file found.")
        popup.dismiss()

class ViewDataScreen(Screen):
    def on_pre_enter(self):
        self.ids.data_table.clear_widgets()
        self.ids.data_table.add_widget(Label(text="Section", font_size="14sp"))
        self.ids.data_table.add_widget(Label(text="Value", font_size="14sp"))
        self.ids.data_table.add_widget(Label(text="Timestamp/Date", font_size="14sp"))

        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                data = json.load(f)

            # Display pain data
            for section, entries in data.items():
                if section == "sleep_data":
                    continue  # Skip sleep_data here
                for entry in entries:
                    self.ids.data_table.add_widget(Label(text=section, font_size="12sp"))
                    self.ids.data_table.add_widget(Label(text=str(entry["value"]), font_size="12sp"))
                    self.ids.data_table.add_widget(Label(text=entry["timestamp"], font_size="12sp"))

            # Display sleep data separately
            if "sleep_data" in data:
                for entry in data["sleep_data"]:
                    self.ids.data_table.add_widget(Label(text="Sleep", font_size="12sp"))
                    sleep_text = f"{entry['hours_slept']} hrs, Quality: {entry['sleep_quality']}"
                    self.ids.data_table.add_widget(Label(text=sleep_text, font_size="12sp"))
                    self.ids.data_table.add_widget(Label(text=entry["date"], font_size="12sp"))
        else:
            self.ids.data_table.add_widget(Label(text="No data found"))
            self.ids.data_table.add_widget(Label(text=""))
            self.ids.data_table.add_widget(Label(text=""))


class PlotScreen(Screen):
    def on_pre_enter(self):
        self.ids.plot_container.clear_widgets()

        if not os.path.exists(DATA_FILE):
            return

        with open(DATA_FILE, "r") as f:
            data = json.load(f)

        fig, ax = plt.subplots()
        cmap = plt.get_cmap("tab10")

        section_keys = [k for k in data.keys() if k != "sleep_data"]

        for i, section in enumerate(section_keys):
            entries = sorted(data[section], key=lambda e: e["timestamp"])
            times = [datetime.strptime(e["timestamp"], "%Y-%m-%d %H:%M:%S") for e in entries]
            values = [e["value"] for e in entries]

            if times and values:
                ax.plot(times, values, label=section, color=cmap(i % 10))

        ax.set_title("Pain Over Time")
        ax.set_xlabel("Time")
        ax.set_ylabel("Pain Value (0–10)")
        ax.legend()
        ax.grid(True)

        canvas = FigureCanvasKivyAgg(fig)
        self.ids.plot_container.add_widget(canvas)


class StatsScreen(Screen):
    def on_pre_enter(self):
        self.ids.stats_box.clear_widgets()

        if not os.path.exists(DATA_FILE):
            self.ids.stats_box.add_widget(Label(text="No data found."))
            return

        with open(DATA_FILE, "r") as f:
            data = json.load(f)

        total_entries = 0
        section_averages = {}
        highest_score = -1
        highest_entry = None

        for section, entries in data.items():
            if section == "sleep_data":
                continue  # Skip sleep_data here
            values = [e["value"] for e in entries]
            timestamps = [e["timestamp"] for e in entries]
            total_entries += len(values)

            if values:
                avg = sum(values) / len(values)
                section_averages[section] = avg

                max_val = max(values)
                if max_val > highest_score:
                    highest_score = max_val
                    idx = values.index(max_val)
                    highest_entry = (section, max_val, timestamps[idx])

        # Display pain stats
        self.ids.stats_box.add_widget(Label(text=f"Total pain entries: {total_entries}", font_size="16sp"))

        for section, avg in section_averages.items():
            self.ids.stats_box.add_widget(Label(text=f"{section}: avg pain {avg:.2f}", font_size="14sp"))

        if highest_entry:
            s, v, t = highest_entry
            self.ids.stats_box.add_widget(Label(
                text=f"Highest recorded: {v:.1f} in {s} at {t}",
                font_size="14sp", color=(1, 0.4, 0.4, 1)
            ))

        if section_averages:
            best = min(section_averages.items(), key=lambda x: x[1])
            self.ids.stats_box.add_widget(Label(
                text=f"Lowest average: {best[0]} ({best[1]:.2f})",
                font_size="14sp", color=(0.6, 1, 0.6, 1)
            ))

        # Display today's sleep data if present
        today_str = datetime.now().strftime("%Y-%m-%d")
        sleep_entries_today = [
            entry for entry in data.get("sleep_data", [])
            if entry["date"] == today_str
        ]

        if sleep_entries_today:
            sleep_entry = sleep_entries_today[-1]  # latest sleep data entry today
            sleep_text = f"Today's Sleep: {sleep_entry['hours_slept']} hrs, Quality {sleep_entry['sleep_quality']}"
        else:
            sleep_text = "No sleep data logged today."

        self.ids.stats_box.add_widget(Label(
            text=sleep_text,
            font_size="14sp", color=(0.4, 0.6, 1, 1)
        ))


class SleepInputScreen(Screen):
    hours_slept = StringProperty("")
    sleep_quality = StringProperty("")

    def set_quality(self, quality):
        self.sleep_quality = quality
        self.ids.quality_label.text = f"Quality selected: {quality}"

    def save_sleep_data(self):
        if not self.ids.hours_input.text or not self.sleep_quality:
            self.ids.quality_label.text = "Enter hours and select quality!"
            return

        try:
            hours = float(self.ids.hours_input.text)
            if not (0 <= hours <= 24):
                raise ValueError
        except ValueError:
            self.ids.quality_label.text = "Enter valid hours (0–24)."
            return

        sleep_entry = {
            "hours_slept": hours,
            "sleep_quality": int(self.sleep_quality),
            "date": datetime.now().strftime("%Y-%m-%d")
        }

        data = self.load_data()
        data.setdefault("sleep_data", []).append(sleep_entry)
        self.write_data(data)

        self.hours_slept = ""
        self.sleep_quality = ""
        self.ids.hours_input.text = ""
        self.ids.quality_label.text = "Saved!"

        self.manager.current = "home"

    @staticmethod
    def load_data():
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        return {}

    @staticmethod
    def write_data(data):
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)


if __name__ == "__main__":
    MeasurementApp().run()
