import json
import os
from datetime import datetime
import csv
import matplotlib.pyplot as plt
from kivy.utils import platform
from kivy.app import App
from kivy.lang import Builder
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.properties import StringProperty
from kivy.core.window import Window
from kivy.uix.popup import Popup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy_garden.matplotlib.backend_kivyagg import FigureCanvasKivyAgg

Window.size = (400, 600)

DATA_FILE = "data.json"

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

    def save_measurement(self):
        try:
            value = float(self.entered_value)
            if not (0 <= value <= 10):
                raise ValueError
        except ValueError:
            self.ids.status_label.text = "Please enter a number between 0 and 10"
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = {"value": value, "timestamp": timestamp}

        data = self.load_data()
        data.setdefault(self.selected_section, []).append(entry)
        self.write_data(data)

        self.ids.status_label.text = f"Saved {value} to {self.selected_section}"
        self.entered_value = ""
        self.ids.display_value.text = ""

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
        return sm

    def export_csv(self):
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
            writer.writerow(["section", "value", "timestamp"])
            for section, entries in data.items():
                for entry in entries:
                    writer.writerow([section, entry["value"], entry["timestamp"]])

        print(f"Data exported to: {csv_path}")

        if platform == "android":
            from jnius import autoclass, cast
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            File = autoclass("java.io.File")
            intent = Intent(Intent.ACTION_SEND)
            file_obj = File(csv_path)
            uri = Uri.fromFile(file_obj)

            intent.setType("text/csv")
            intent.putExtra(Intent.EXTRA_SUBJECT, "Pain Measurement Data")
            intent.putExtra(Intent.EXTRA_TEXT, "Attached is the exported CSV data.")
            intent.putExtra(Intent.EXTRA_STREAM, cast("android.os.Parcelable", uri))

            currentActivity = autoclass("org.kivy.android.PythonActivity").mActivity
            currentActivity.startActivity(Intent.createChooser(intent, "Send CSV via..."))

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
        self.ids.data_table.add_widget(Label(text="Timestamp", font_size="14sp"))

        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                data = json.load(f)

            for section, entries in data.items():
                for entry in entries:
                    self.ids.data_table.add_widget(Label(text=section, font_size="12sp"))
                    self.ids.data_table.add_widget(Label(text=str(entry["value"]), font_size="12sp"))
                    self.ids.data_table.add_widget(Label(text=entry["timestamp"], font_size="12sp"))
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
        section_keys = list(data.keys())
        cmap = plt.get_cmap("tab10")

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

if __name__ == "__main__":
    MeasurementApp().run()
