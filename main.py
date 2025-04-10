import json
import os
import csv
import logging
from datetime import datetime, timedelta
import math

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

# Uncomment to set a fixed window size for desktop testing
# Window.size = (600, 800)

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
    """Home screen for navigating to different app pages."""
    pass


class DataEntryScreen(Screen):
    """
    Screen for selecting which body section to log a measurement for.
    """

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
    """
    Screen for entering measurement data.

    Measurements (other than sleep) are rounded down to the nearest hour.
    """
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

    def round_down_to_hour(self, dt):
        """
        Round the given datetime object down to the current hour.

        :param dt: The datetime object to round.
        :type dt: datetime
        :return: A datetime object rounded down to the start of the hour.
        :rtype: datetime
        """
        return dt.replace(minute=0, second=0, microsecond=0)

    def save_measurement(self):
        """
        Validate and save a measurement.

        Logs an error if the input is invalid, otherwise saves the measurement.

        :return: True if the measurement is saved successfully, otherwise False.
        :rtype: bool
        """
        app = App.get_running_app()
        app.logger.debug("Attempting to save measurement: %s for section %s",
                         self.entered_value, self.selected_section)
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

        rounded_timestamp = self.round_down_to_hour(datetime.now())
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
            app.logger.info("New measurement saved: %s for section %s",
                            entry, self.selected_section)

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
                logger.debug("Data loaded successfully with %d total entries",
                             sum(len(v) for v in data.values() if isinstance(v, list)))
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


class ActivityScreen(Screen):
    """
    Screen for logging an activity.

    Provides a spinner for activity level (1–5) and a text input for the activity name.
    If an activity for the current hour already exists, appends the entry to the list.
    If no activity name is given, a blank is stored.
    """

    def save_activity(self):
        """
        Save the activity for the current hour.
        """
        now = datetime.now()
        ts = now.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
        level = self.ids.activity_level_spinner.text  # Expecting a number as string
        name = self.ids.activity_name_input.text.strip()
        entry = {"activity_level": level, "activity_name": name}
        data = MeasurementInputScreen.load_data()
        if "activity_data" not in data:
            data["activity_data"] = {}
        if ts in data["activity_data"]:
            data["activity_data"][ts].append(entry)
        else:
            data["activity_data"][ts] = [entry]
        MeasurementInputScreen.write_data(data)
        self.manager.current = "home"

    def return_without_save(self):
        """
        Return to the home screen without saving.
        """
        self.manager.current = "home"


class NotesScreen(Screen):
    """
    Screen for editing notes for the current hour.

    Displays current notes (if any) on entering and saves updates.
    """

    def on_pre_enter(self):
        """
        Load notes for the current hour when the screen is entered.
        """
        ts = datetime.now().replace(minute=0, second=0, microsecond=0) \
            .strftime("%Y-%m-%d %H:%M:%S")
        data = MeasurementInputScreen.load_data()
        note_text = ""
        if "notes_data" in data and ts in data["notes_data"]:
            note_text = data["notes_data"][ts]
        self.ids.notes_input.text = note_text

    def save_notes(self):
        """
        Save the notes for the current hour and return to home.
        """
        ts = datetime.now().replace(minute=0, second=0, microsecond=0) \
            .strftime("%Y-%m-%d %H:%M:%S")
        data = MeasurementInputScreen.load_data()
        if "notes_data" not in data:
            data["notes_data"] = {}
        data["notes_data"][ts] = self.ids.notes_input.text
        MeasurementInputScreen.write_data(data)
        self.manager.current = "home"


from kivy.metrics import dp
from kivy.uix.scrollview import ScrollView
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
# (Ensure other required imports are already present)

class ViewDataScreen(Screen):
    """
    Screen for viewing saved data.

    The displayed data format mimics the export CSV:
      a) A main row with columns:
         Timestamp (dd/mm/yyyy hh:mm), Activity Value, Activity, RU, RL, LU, LL, Axial, Head.
      b) If any notes exist for that timestamp, a second row is added showing:
         "Notes: <text>"

    A ScrollView is used to allow scrolling when many records are present.
    """

    def on_pre_enter(self):
        """
        Populate the view with combined pain, activity and notes data in a scrollable layout.
        """
        # Clear previous records from the container
        self.ids.data_box.clear_widgets()

        # Header row for main fields
        header_titles = ["Timestamp", "A-Value", "Activity", "RU", "RL", "LU", "LL", "Axial", "Head"]
        header_layout = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(30), spacing=5)
        # Define fixed widths for each header label
        header_widths = [dp(100), dp(60), dp(80), dp(40), dp(40), dp(40), dp(40), dp(50), dp(50)]
        for title, width in zip(header_titles, header_widths):
            header_label = Label(text=title, font_size="12sp", size_hint_x=None, width=width)
            header_layout.add_widget(header_label)
        self.ids.data_box.add_widget(header_layout)

        # Load data from file
        data = {}
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r") as f:
                    data = json.load(f)
            except Exception as e:
                App.get_running_app().logger.exception("Error loading data for view: %s", e)

        # Define the pain measurement sections
        pain_sections = ["RU", "RL", "LU", "LL", "Axial", "Head"]

        # Build combined rows keyed by the rounded timestamp.
        combined_rows = {}
        # Process pain measurements (from body sections)
        for section in pain_sections:
            if section in data and isinstance(data[section], list):
                for entry in data[section]:
                    try:
                        dt = datetime.strptime(entry["timestamp"], "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        continue
                    if dt not in combined_rows:
                        combined_rows[dt] = {"pain": {}, "activity_levels": [], "activity_names": [], "notes": ""}
                    combined_rows[dt]["pain"][section] = entry["value"]

        # Process activity data
        if "activity_data" in data:
            for ts_str, entries in data["activity_data"].items():
                try:
                    dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    continue
                if dt not in combined_rows:
                    combined_rows[dt] = {"pain": {}, "activity_levels": [], "activity_names": [], "notes": ""}
                for entry in entries:
                    combined_rows[dt]["activity_levels"].append(str(entry.get("activity_level", "")))
                    combined_rows[dt]["activity_names"].append(entry.get("activity_name", ""))

        # Process notes data
        if "notes_data" in data:
            for ts_str, note in data["notes_data"].items():
                try:
                    dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    continue
                if dt not in combined_rows:
                    combined_rows[dt] = {"pain": {}, "activity_levels": [], "activity_names": [], "notes": ""}
                combined_rows[dt]["notes"] = note

        # Sort the combined rows by timestamp ascending and add them to the layout
        for dt in sorted(combined_rows.keys()):
            ts_formatted = dt.strftime("%d/%m/%Y %H:%M")
            act_levels = combined_rows[dt]["activity_levels"]
            act_names = combined_rows[dt]["activity_names"]
            act_val_str = f"[{','.join(act_levels)}]" if act_levels else ""
            act_names_str = f"[{','.join(act_names)}]" if act_names else ""
            # Retrieve pain measurements with blank if not present
            pain_vals = [str(combined_rows[dt]["pain"].get(sec, "")) for sec in pain_sections]

            # Create the main row container inside a HorizontalScrollView
            hs_view = ScrollView(size_hint_y=None, height=dp(30), do_scroll_x=True, do_scroll_y=False)
            main_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(30), spacing=5)
            # Corresponding fixed widths for each column (same as header)
            col_widths = [dp(100), dp(60), dp(80), dp(40), dp(40), dp(40), dp(40), dp(50), dp(50)]
            row_fields = [ts_formatted, act_val_str, act_names_str] + pain_vals
            for field, width in zip(row_fields, col_widths):
                lbl = Label(text=field, font_size="12sp", size_hint_x=None, width=width)
                main_row.add_widget(lbl)
            hs_view.add_widget(main_row)
            self.ids.data_box.add_widget(hs_view)

            # If there are notes, display them in a second row spanning full width.
            note_text = combined_rows[dt]["notes"]
            if note_text.strip():
                note_label = Label(text="Notes: " + note_text, font_size="11sp", halign="left",
                                   size_hint_y=None, height="25dp")
                self.ids.data_box.add_widget(note_label)

            # Add an optional separator between records
            separator = Label(text=" ", size_hint_y=None, height=dp(10))
            self.ids.data_box.add_widget(separator)


class PlotScreen(Screen):
    """
    Screen for plotting a spider (radar) diagram of the pain measurements.

    For each hour, a line is plotted representing RU, RL, LU, LL, Axial, and Head.
    If any region is missing a value, 0 is assumed.
    """

    def on_pre_enter(self):
        """
        Generate and display a radar chart with a line per hour.
        """
        self.ids.plot_container.clear_widgets()
        if not os.path.exists(DATA_FILE):
            return

        try:
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
            # Define pain regions
            pain_sections = ["RU", "RL", "LU", "LL", "Axial", "Head"]
            # Build combined pain data keyed by timestamp (rounded hour)
            combined = {}
            for section in pain_sections:
                if section in data and isinstance(data[section], list):
                    for entry in data[section]:
                        try:
                            dt = datetime.strptime(entry["timestamp"], "%Y-%m-%d %H:%M:%S")
                        except Exception:
                            continue
                        if dt not in combined:
                            # Initialise all regions to 0 by default.
                            combined[dt] = {s: 0 for s in pain_sections}
                        combined[dt][section] = entry.get("value", 0)
            if not combined:
                return
            sorted_timestamps = sorted(combined.keys())
            N = len(pain_sections)
            # Compute angles for radar chart
            angles = [n / float(N) * 2 * math.pi for n in range(N)]
            angles += angles[:1]  # Repeat first angle to close the loop

            fig = plt.figure()
            ax = plt.subplot(111, polar=True)
            # Offset so first axis is at the top
            ax.set_theta_offset(math.pi / 2)
            ax.set_theta_direction(-1)
            plt.xticks(angles[:-1], pain_sections)

            # Use a colour map to differentiate lines
            cmap = plt.get_cmap("viridis")
            total = len(sorted_timestamps)
            for i, dt in enumerate(sorted_timestamps):
                values = [combined[dt][s] for s in pain_sections]
                values += values[:1]  # Close the loop
                colour = cmap(i / float(total))
                ax.plot(angles, values, label=dt.strftime("%d/%m %H:%M"), color=colour)
                ax.fill(angles, values, alpha=0.1, color=colour)
            ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1))
            ax.grid(True)
            canvas = FigureCanvasKivyAgg(fig)
            self.ids.plot_container.add_widget(canvas)
        except Exception as e:
            App.get_running_app().logger.exception("Error generating radar plot: %s", e)


class StatsScreen(Screen):
    """
    Screen for displaying statistics based on pain and sleep data.

    Now includes a computed metric "Pain (Arb.)" defined as:
    (average of [RU, RL, LU, LL, Axial, Head] × number of non-zero scores) / 3.
    """

    def on_pre_enter(self):
        """
        Calculate and display statistics.
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
            # Current stat calculations for each section (excluding sleep data)
            for section, entries in data.items():
                if section == "sleep_data":
                    continue
                if isinstance(entries, list):
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
                self.ids.stats_box.add_widget(
                    Label(text=f"Highest recorded: {v:.1f} in {s} at {t}", font_size="14sp", color=(1, 0.4, 0.4, 1)))
            if section_averages:
                best = min(section_averages.items(), key=lambda x: x[1])
                self.ids.stats_box.add_widget(
                    Label(text=f"Lowest average: {best[0]} ({best[1]:.2f})", font_size="14sp", color=(0.6, 1, 0.6, 1)))

            # --- New Calculation for Pain (Arb.) ---
            # Combine pain measurements for the six regions keyed by rounded timestamp.
            pain_sections = ["RU", "RL", "LU", "LL", "Axial", "Head"]
            combined = {}
            for sec in pain_sections:
                if sec in data and isinstance(data[sec], list):
                    for entry in data[sec]:
                        try:
                            dt = datetime.strptime(entry["timestamp"], "%Y-%m-%d %H:%M:%S")
                        except Exception:
                            continue
                        if dt not in combined:
                            combined[dt] = {s: 0 for s in pain_sections}
                        combined[dt][sec] = entry.get("value", 0)
            hourly_pain_indices = []
            for dt, vals in combined.items():
                # Use 0 for missing regions.
                total = sum(vals[s] for s in pain_sections)
                avg = total / 6.0
                nonzero_count = sum(1 for s in pain_sections if vals[s] > 0)
                pain_arb = (avg * nonzero_count) / 3.0
                hourly_pain_indices.append(pain_arb)
            if hourly_pain_indices:
                overall_pain_arb = sum(hourly_pain_indices) / len(hourly_pain_indices)
            else:
                overall_pain_arb = 0
            self.ids.stats_box.add_widget(
                Label(text=f"Pain (Arb.): {overall_pain_arb:.2f}", font_size="14sp", color=(0.4, 0.8, 1, 1)))
            # ----------------------------------------------------

            # Sleep data as before
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
    """
    Screen for entering sleep data.
    """
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


class MeasurementApp(App):
    """
    Main application class.
    """

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
        sm.add_widget(ActivityScreen(name="activity"))
        sm.add_widget(NotesScreen(name="notes"))
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
        Export pain and activity data to CSV in the required format.

        The exported columns are:
        Timestamp (dd/mm/yyyy hh:mm), Activity Value, Activity, RU, RL, LU, LL, Axial, Head, Notes

        Sleep data is appended separately.

        :return: The absolute path to the saved CSV file.
        :rtype: str
        """
        logger = App.get_running_app().logger
        logger.debug("Exporting CSV to internal storage with updated format.")
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
        else:
            data = {}

        # Define the pain sections in the desired order.
        pain_sections = ["RU", "RL", "LU", "LL", "Axial", "Head"]
        # Dictionary to hold combined data rows for each timestamp.
        combined_rows = {}

        # Process pain measurements
        for section in pain_sections:
            if section in data and isinstance(data[section], list):
                for entry in data[section]:
                    try:
                        dt = datetime.strptime(entry["timestamp"], "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        continue
                    if dt not in combined_rows:
                        combined_rows[dt] = {"pain": {}, "activity_levels": [], "activity_names": [], "notes": ""}
                    combined_rows[dt]["pain"][section] = entry["value"]

        # Process activity data
        if "activity_data" in data:
            for ts_str, entries in data["activity_data"].items():
                try:
                    dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    continue
                if dt not in combined_rows:
                    combined_rows[dt] = {"pain": {}, "activity_levels": [], "activity_names": [], "notes": ""}
                for entry in entries:
                    combined_rows[dt]["activity_levels"].append(str(entry.get("activity_level", "")))
                    combined_rows[dt]["activity_names"].append(entry.get("activity_name", ""))

        # Process notes data
        if "notes_data" in data:
            for ts_str, note in data["notes_data"].items():
                try:
                    dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    continue
                if dt not in combined_rows:
                    combined_rows[dt] = {"pain": {}, "activity_levels": [], "activity_names": [], "notes": ""}
                combined_rows[dt]["notes"] = note

        # Prepare the CSV file
        app = App.get_running_app()
        export_dir = app.user_data_dir
        os.makedirs(export_dir, exist_ok=True)
        csv_path = os.path.join(export_dir, "pain_management.csv")
        if os.path.exists(csv_path):
            os.remove(csv_path)

        try:
            with open(csv_path, "w", newline="") as csvfile:
                writer = csv.writer(csvfile)
                # Write header row for pain and activity data
                header = ["Timestamp (dd/mm/yyyy hh:mm)", "Activity Value", "Activity",
                          "RU", "RL", "LU", "LL", "Axial", "Head", "Notes"]
                writer.writerow(header)

                # For each combined row (sorted by timestamp)
                for dt in sorted(combined_rows.keys()):
                    # Format the timestamp as required
                    ts_formatted = dt.strftime("%d/%m/%Y %H:%M")
                    act_levels = combined_rows[dt]["activity_levels"]
                    act_names = combined_rows[dt]["activity_names"]
                    # Join lists into strings, enclosed in square brackets if not empty
                    act_val_str = f"[{','.join(act_levels)}]" if act_levels else ""
                    act_names_str = f"[{','.join(act_names)}]" if act_names else ""
                    # Get pain values for each section
                    pain_vals = [combined_rows[dt]["pain"].get(sec, "") for sec in pain_sections]
                    # Get notes value
                    note_val = combined_rows[dt]["notes"]
                    row = [ts_formatted, act_val_str, act_names_str] + pain_vals + [note_val]
                    writer.writerow(row)

                # Append sleep data as before.
                if "sleep_data" in data:
                    writer.writerow([])
                    writer.writerow(["Sleep Data"])
                    writer.writerow(["date", "hours_slept", "sleep_quality"])
                    for entry in data["sleep_data"]:
                        writer.writerow(
                            [entry.get("date", ""), entry.get("hours_slept", ""), entry.get("sleep_quality", "")])
            logger.info("CSV exported successfully to: %s", csv_path)
        except Exception as e:
            logger.exception("Error exporting CSV: %s", e)
        return csv_path

    def share_exported_csv(self):
        """
        Share the exported CSV file via the native share functionality.
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
        Display a popup indicating the CSV export location with extra padding.
        """
        path = self.export_csv_to_internal()
        layout = BoxLayout(orientation='vertical', padding=20, spacing=10)
        scroll = ScrollView(size_hint=(1, None), size=("260dp", "100dp"))
        inner_layout = BoxLayout(orientation='vertical', padding=(20, 50), size_hint_y=None)
        message = Label(
            text=f"{path}",
            halign="left",
            valign="middle",
            size_hint_y=None
        )
        message.bind(width=lambda instance, value: setattr(instance, 'text_size', (value, None)))
        message.bind(texture_size=lambda instance, value: setattr(instance, 'height', value[1]))
        inner_layout.add_widget(message)
        inner_layout.bind(minimum_height=inner_layout.setter('height'))
        scroll.add_widget(inner_layout)
        layout.add_widget(scroll)
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


if __name__ == "__main__":
    MeasurementApp().run()
