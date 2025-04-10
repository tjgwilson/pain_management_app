import json
import os
import csv
import logging
from datetime import datetime, timedelta

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
from kivy.uix.scrollview import ScrollView

if platform in ('android', 'ios'):
    try:
        from plyer import share
    except ImportError:
        share = None
else:
    share = None  # Share functionality not available on desktop

# Uncomment to set a fixed window size for desktop testing
Window.size = (600, 800)

DATA_FILE = "data.json"

def get_rainbow_colour(index, total, alpha=0.3):
    """
    Return a gentle transparent colour from the rainbow colormap.

    :param index: The current index.
    :type index: int or float
    :param total: The total number of items.
    :type total: int or float
    :param alpha: Transparency value (default is 0.3).
    :type alpha: float
    :return: A list representing the RGBA colour.
    :rtype: list
    """
    cmap = get_cmap("rainbow")
    r, g, b, _ = cmap(index / max(1, total - 1))
    return [r, g, b, alpha]

class HomeScreen(Screen):
    pass

class DataEntryScreen(Screen):
    def open_input_screen(self, section_tag):
        """
        Open the measurement input screen for a specified section.

        :param section_tag: The section for which data is to be entered.
        :type section_tag: str
        :return: None
        """
        app = App.get_running_app()
        app.logger.info("Switching to input screen for section: %s", section_tag)
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
        """
        Append a number character to the entered value.

        :param char: The character to append.
        :type char: str
        :return: None
        """
        if len(self.entered_value) < 4:
            self.entered_value += char
            self.ids.display_value.text = self.entered_value

    def delete_last(self):
        """
        Delete the last character from the entered value.

        :return: None
        """
        self.entered_value = self.entered_value[:-1]
        self.ids.display_value.text = self.entered_value

    def round_to_next_hour(self, dt):
        """
        Round the given datetime object to the next hour.

        :param dt: The datetime object to round.
        :type dt: datetime
        :return: A datetime object rounded to the start of the next hour.
        :rtype: datetime
        """
        return (dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))

    def save_measurement(self):
        """
        Validate and save a measurement.

        Logs an error if the input is invalid, otherwise saves the measurement.

        :return: True if the measurement is saved successfully, otherwise False.
        :rtype: bool
        """
        app = App.get_running_app()
        app.logger.debug("Attempting to save measurement: %s for section %s", self.entered_value, self.selected_section)
        if not self.entered_value.strip():
            app.logger.debug("No value entered, skipping save.")
            return True

        try:
            value = float(self.entered_value)
            if not (0 <= value <= 10):
                raise ValueError
        except ValueError:
            if 'status_label' in self.ids:
                self.ids.status_label.text = "Please enter a number between 0 and 10"
            app.logger.warning("Invalid measurement input: %s", self.entered_value)
            return False

        rounded_timestamp = self.round_to_next_hour(datetime.now())
        timestamp_str = rounded_timestamp.strftime("%Y-%m-%d %H:%M:%S")
        entry = {"value": value, "timestamp": timestamp_str}

        data = self.load_data()

        # Check if an entry for the same hour exists and update if necessary
        section_entries = data.get(self.selected_section, [])
        for existing_entry in section_entries:
            if existing_entry["timestamp"] == timestamp_str:
                if existing_entry["value"] < value:
                    existing_entry["value"] = value
                    app.logger.debug("Updated entry with a higher value: %s", value)
                break
        else:
            section_entries.append(entry)
            app.logger.info("New measurement saved: %s for section %s", entry, self.selected_section)

        data[self.selected_section] = section_entries
        self.write_data(data)

        self.entered_value = ""
        if 'display_value' in self.ids:
            self.ids.display_value.text = ""
        return True

    def save_and_return(self):
        """
        Save the measurement and return to the data entry screen if successful.

        :return: None
        """
        if self.save_measurement():
            self.manager.current = "data_entry"

    @staticmethod
    def load_data():
        """
        Load the data from the JSON file.

        :return: The loaded data as a dictionary.
        :rtype: dict
        """
        logger = App.get_running_app().logger
        logger.debug("Loading data from %s", DATA_FILE)
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r") as f:
                    data = json.load(f)
                logger.debug("Data loaded successfully with %d total entries", sum(len(v) for v in data.values()))
                return data
            except Exception as e:
                logger.exception("Error loading data: %s", e)
        return {}

    @staticmethod
    def write_data(data):
        """
        Write data to the JSON file.

        :param data: The data dictionary to write.
        :type data: dict
        :return: None
        """
        logger = App.get_running_app().logger
        logger.debug("Writing data to %s", DATA_FILE)
        try:
            with open(DATA_FILE, "w") as f:
                json.dump(data, f, indent=2)
            logger.info("Data written successfully.")
        except Exception as e:
            logger.exception("Error writing data: %s", e)

class MeasurementApp(App):
    def build(self):
        """
        Build the application UI, set up logging and initialise the screen manager.

        :return: The root widget (ScreenManager).
        :rtype: ScreenManager
        """
        Builder.load_file("main.kv")
        self.setup_logger()
        sm = ScreenManager()
        sm.add_widget(HomeScreen(name="home"))
        sm.add_widget(DataEntryScreen(name="data_entry"))
        sm.add_widget(MeasurementInputScreen(name="input_screen"))
        sm.add_widget(ViewDataScreen(name="view_data"))
        sm.add_widget(PlotScreen(name="plot_screen"))
        sm.add_widget(StatsScreen(name="stats_screen"))
        sm.add_widget(SleepInputScreen(name="sleep_input"))
        self.logger.info("Application UI built successfully.")
        return sm

    def setup_logger(self):
        """
        Set up logging to a file in the app's internal storage.

        The log file (app.log) is saved in the app's user data directory.
        """
        log_file = os.path.join(self.user_data_dir, "app.log")
        logger = logging.getLogger("MeasurementAppLogger")
        logger.setLevel(logging.DEBUG)
        if logger.hasHandlers():
            logger.handlers.clear()
        fh = logging.FileHandler(log_file, mode='w')
        fh.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        sh = logging.StreamHandler()
        sh.setLevel(logging.INFO)
        sh.setFormatter(formatter)
        logger.addHandler(sh)
        self.logger = logger
        logger.info("Logger initialised. Log file saved at: %s", log_file)

    @staticmethod
    def get_rainbow_colour(index, total):
        """
        Return a rainbow colour using the specified index.

        :param index: The current index.
        :type index: int or float
        :param total: The total number of items.
        :type total: int or float
        :return: A list representing the RGBA colour.
        :rtype: list
        """
        return get_rainbow_colour(index, total)

    @staticmethod
    def animate_button(button):
        """
        Animate the given button using a scaling effect.

        :param button: The button to animate.
        :type button: kivy.uix.button.Button
        :return: None
        """
        anim = Animation(scale=1.1, duration=0.05) + Animation(scale=1.0, duration=0.05)
        anim.start(button)

    @staticmethod
    def export_csv_to_internal():
        """
        Export data as CSV to the app's internal storage and return the file path.

        :return: The absolute path to the saved CSV file.
        :rtype: str
        """
        logger = App.get_running_app().logger
        logger.debug("Exporting CSV to internal storage.")
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
        else:
            data = {}

        app = App.get_running_app()
        export_dir = app.user_data_dir
        os.makedirs(export_dir, exist_ok=True)
        csv_path = os.path.join(export_dir, "pain_management.csv")
        if os.path.exists(csv_path):
            os.remove(csv_path)
        try:
            with open(csv_path, "w", newline="") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["section", "value", "timestamp"])
                for section, entries in data.items():
                    if section != "sleep_data":
                        for entry in entries:
                            writer.writerow([section, entry["value"], entry["timestamp"]])
                if "sleep_data" in data:
                    writer.writerow([])
                    writer.writerow(["Sleep Data"])
                    writer.writerow(["date", "hours_slept", "sleep_quality"])
                    for entry in data["sleep_data"]:
                        writer.writerow([entry["date"], entry["hours_slept"], entry["sleep_quality"]])
            logger.info("CSV exported successfully to: %s", csv_path)
        except Exception as e:
            logger.exception("Error exporting CSV: %s", e)
        return csv_path

    def share_exported_csv(self):
        """
        Share the exported CSV file via the native share functionality.

        :return: None
        """
        try:
            csv_path = self.export_csv_to_internal()
            if share:
                share.share(filepath=csv_path,
                            title="Share CSV",
                            text="Here is my pain management data CSV file.")
                self.logger.info("CSV shared successfully.")
            else:
                self.logger.warning("Sharing functionality is not available on this platform.")
        except Exception as e:
            self.logger.error("Error sharing CSV: %s", e)

    def export_popup(self):
        """
        Display a popup indicating the CSV export location with extra padding between the text and the container.

        The export path message is wrapped in a ScrollView and then inside a BoxLayout that adds padding.
        This ensures the text is not too close to the edges.

        :return: None
        """
        path = self.export_csv_to_internal()
        layout = BoxLayout(orientation='vertical', padding=20, spacing=10)

        # Create a ScrollView to safely contain long text.
        scroll = ScrollView(size_hint=(1, None), size=("260dp", "100dp"))
        # Wrap the message label in an inner BoxLayout with extra padding for spacing.
        inner_layout = BoxLayout(orientation='vertical', padding=(20, 50), size_hint_y=None)
        message = Label(
            text=f"{path}",
            halign="left",
            valign="middle",
            size_hint_y=None
        )
        # Bind the label's width to its text_size to force wrapping, and update its height from the texture.
        message.bind(width=lambda instance, value: setattr(instance, 'text_size', (value, None)))
        message.bind(texture_size=lambda instance, value: setattr(instance, 'height', value[1]))
        inner_layout.add_widget(message)
        # Update inner_layout height to fit the content.
        inner_layout.bind(minimum_height=inner_layout.setter('height'))
        scroll.add_widget(inner_layout)
        layout.add_widget(scroll)

        # Add a button container with appropriate spacing.
        buttons = BoxLayout(spacing=50, size_hint_y=None, height="48dp")
        confirm_btn = Button(text="OK", background_color=(0.8, 0.1, 0.1, 1))
        buttons.add_widget(confirm_btn)
        layout.add_widget(buttons)

        popup = Popup(title="Saved to:", content=layout,
                      size_hint=(None, None), size=("300dp", "200dp"),
                      auto_dismiss=False)
        confirm_btn.bind(on_release=popup.dismiss)
        popup.open()
        self.logger.info("Data export popup displayed; CSV saved at: %s", path)

    def show_delete_confirmation(self):
        """
        Display a confirmation popup before deleting data.

        :return: None
        """
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
        self.logger.info("Delete confirmation popup displayed.")

    @staticmethod
    def delete_data(popup):
        """
        Delete the JSON data file and dismiss the popup.

        :param popup: The popup widget to dismiss.
        :type popup: kivy.uix.popup.Popup
        :return: None
        """
        logger = App.get_running_app().logger
        if os.path.exists(DATA_FILE):
            os.remove(DATA_FILE)
            logger.info("Data file '%s' deleted.", DATA_FILE)
        else:
            logger.warning("Attempt to delete non-existent data file.")
        popup.dismiss()

class ViewDataScreen(Screen):
    def on_pre_enter(self):
        """
        Populate the data table with saved measurements and sleep data.

        :return: None
        """
        self.ids.data_table.clear_widgets()
        self.ids.data_table.add_widget(Label(text="Section", font_size="14sp"))
        self.ids.data_table.add_widget(Label(text="Value", font_size="14sp"))
        self.ids.data_table.add_widget(Label(text="Timestamp/Date", font_size="14sp"))

        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r") as f:
                    data = json.load(f)
                for section, entries in data.items():
                    if section == "sleep_data":
                        continue
                    for entry in entries:
                        self.ids.data_table.add_widget(Label(text=section, font_size="12sp"))
                        self.ids.data_table.add_widget(Label(text=str(entry["value"]), font_size="12sp"))
                        self.ids.data_table.add_widget(Label(text=entry["timestamp"], font_size="12sp"))
                if "sleep_data" in data:
                    for entry in data["sleep_data"]:
                        self.ids.data_table.add_widget(Label(text="Sleep", font_size="12sp"))
                        sleep_text = f"{entry['hours_slept']} hrs, Quality: {entry['sleep_quality']}"
                        self.ids.data_table.add_widget(Label(text=sleep_text, font_size="12sp"))
                        self.ids.data_table.add_widget(Label(text=entry["date"], font_size="12sp"))
            except Exception as e:
                App.get_running_app().logger.exception("Error populating data table: %s", e)
        else:
            self.ids.data_table.add_widget(Label(text="No data found"))
            self.ids.data_table.add_widget(Label(text=""))
            self.ids.data_table.add_widget(Label(text=""))

class PlotScreen(Screen):
    def on_pre_enter(self):
        """
        Generate and display a plot of pain values over time.

        :return: None
        """
        self.ids.plot_container.clear_widgets()
        if not os.path.exists(DATA_FILE):
            return

        try:
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
        except Exception as e:
            App.get_running_app().logger.exception("Error generating plot: %s", e)

class StatsScreen(Screen):
    def on_pre_enter(self):
        """
        Calculate and display statistics based on pain and sleep data.

        :return: None
        """
        self.ids.stats_box.clear_widgets()
        if not os.path.exists(DATA_FILE):
            self.ids.stats_box.add_widget(Label(text="No data found."))
            return

        try:
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
            total_entries = 0
            section_averages = {}
            highest_score = -1
            highest_entry = None
            for section, entries in data.items():
                if section == "sleep_data":
                    continue
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
            self.ids.stats_box.add_widget(Label(text=f"Total pain entries: {total_entries}", font_size="16sp"))
            for section, avg in section_averages.items():
                self.ids.stats_box.add_widget(Label(text=f"{section}: avg pain {avg:.2f}", font_size="14sp"))
            if highest_entry:
                s, v, t = highest_entry
                self.ids.stats_box.add_widget(Label(text=f"Highest recorded: {v:.1f} in {s} at {t}", font_size="14sp", color=(1, 0.4, 0.4, 1)))
            if section_averages:
                best = min(section_averages.items(), key=lambda x: x[1])
                self.ids.stats_box.add_widget(Label(text=f"Lowest average: {best[0]} ({best[1]:.2f})", font_size="14sp", color=(0.6, 1, 0.6, 1)))
            today_str = datetime.now().strftime("%Y-%m-%d")
            sleep_entries_today = [entry for entry in data.get("sleep_data", []) if entry["date"] == today_str]
            if sleep_entries_today:
                sleep_entry = sleep_entries_today[-1]
                sleep_text = f"Today's Sleep: {sleep_entry['hours_slept']} hrs, Quality {sleep_entry['sleep_quality']}"
            else:
                sleep_text = "No sleep data logged today."
            self.ids.stats_box.add_widget(Label(text=sleep_text, font_size="14sp", color=(0.4, 0.6, 1, 1)))
        except Exception as e:
            App.get_running_app().logger.exception("Error calculating statistics: %s", e)

class SleepInputScreen(Screen):
    hours_slept = StringProperty("")
    sleep_quality = StringProperty("")

    def set_quality(self, quality):
        """
        Set the sleep quality based on the user's selection.

        :param quality: The selected sleep quality.
        :type quality: str
        :return: None
        """
        self.sleep_quality = quality
        self.ids.quality_label.text = f"Quality selected: {quality}"

    def save_sleep_data(self):
        """
        Validate and save the sleep data entry.

        :return: None
        """
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
        App.get_running_app().logger.info("Sleep data saved: %s", sleep_entry)
        self.manager.current = "home"

    @staticmethod
    def load_data():
        """
        Load sleep data from the JSON file.

        :return: The loaded data as a dictionary.
        :rtype: dict
        """
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        return {}

    @staticmethod
    def write_data(data):
        """
        Write sleep data to the JSON file.

        :param data: The data to be written.
        :type data: dict
        :return: None
        """
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)

if __name__ == "__main__":
    MeasurementApp().run()
