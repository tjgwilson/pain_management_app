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
from kivy.uix.popup import Popup
from kivy.uix.button import Button
from kivy_garden.matplotlib.backend_kivyagg import FigureCanvasKivyAgg
from kivy.animation import Animation
from kivy.properties import StringProperty
from kivy.metrics import dp
from kivy.uix.scrollview import ScrollView
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.core.window import Window
from kivy.clock import Clock


Window.softinput_mode = 'pan'  # alternatives: 'resize'

# Uncomment to set a fixed window size for desktop testing
# Window.size = (600, 800)

# If on Android, these imports are used for permissions and downloads directory.
if platform == 'android':
    try:
        from android.permissions import request_permissions, Permission
    except ImportError:
        pass
    try:
        from plyer import storagepath
    except ImportError:
        storagepath = None
else:
    storagepath = None


def get_data_file_path() -> str:
    """
    Return the absolute path to the data.json file in the app's user data dir,
    creating the dir if it doesn't exist.

    :return: Absolute path to data.json.
    """
    app = App.get_running_app()
    data_dir = app.user_data_dir
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "data.json")


def round_up_to_hour(dt: datetime) -> str:
    """
    Round the given datetime up to the next hour if it's not already exactly on the hour.

    If dt is already at HH:00:00.000, it is returned unchanged. Otherwise, minutes,
    seconds and microseconds are zeroed and one hour is added. Safely handles
    rolling over past midnight.

    :param dt: The datetime to round.
    :return: A string timestamp in "%Y-%m-%d %H:%M:%S" format, rounded up to the hour.
    """
    if dt.minute == 0 and dt.second == 0 and dt.microsecond == 0:
        rounded = dt
    else:
        rounded = (dt.replace(minute=0, second=0, microsecond=0)
                   + timedelta(hours=1))
    return rounded.strftime("%Y-%m-%d %H:%M:%S")


class HomeScreen(Screen):
    """Home screen for navigating to different app pages."""
    def on_pre_enter(self):
        """
        Force a layout update shortly after the screen is entered,
        so that the widgets are properly drawn and visible.
        """
        # Replace 'home_box' with the actual id of your root layout in the HomeScreen KV rule.
        Clock.schedule_once(lambda dt: self.ids.home_box.do_layout(), 0.1)


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
    historical_timestamp = StringProperty("")

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

    def _show_message(self, msg: str) -> None:
        """
        Show an informational popup with the given message.

        :param msg: The message to display to the user.
        """
        popup = Popup(
            title="Info",
            content=Label(text=msg),
            size_hint=(None, None),
            size=(dp(300), dp(200)),
            auto_dismiss=True
        )
        popup.open()

    def save_measurement(self) -> bool:
        """
        Validate and save a measurement, showing a popup on new, update, or skip.

        :return: True if handled (saved or valid skip), otherwise False.
        """
        app = App.get_running_app()
        app.logger.debug(
            "Attempting to save measurement: %s for section %s",
            self.entered_value, self.selected_section
        )

        # Skip if no value entered
        if not self.entered_value.strip():
            app.logger.debug("No value entered, skipping save.")
            self._show_message("No value entered.")
            return True

        # Validate numeric range
        try:
            value = float(self.entered_value)
            if not (0 <= value <= 10):
                raise ValueError
        except ValueError:
            app.logger.warning("Invalid measurement input: %s", self.entered_value)
            self._show_message("Please enter a number between 0 and 10")
            return False

        if self.historical_timestamp:
            timestamp_str = self.historical_timestamp
        else:
            timestamp_str = round_up_to_hour(datetime.now())
        entry = {"value": value, "timestamp": timestamp_str}

        data = self.load_data()
        section_entries = data.get(self.selected_section, [])
        updated = False

        for existing_entry in section_entries:
            if existing_entry["timestamp"] == timestamp_str:
                updated = True
                if existing_entry["value"] < value:
                    existing_entry["value"] = value
                    app.logger.debug("Updated entry with a higher value: %s", value)
                    self._show_message("Measurement updated.")
                else:
                    app.logger.debug("Existing measurement not lower; skip save.")
                    self._show_message(
                        "Existing measurement\nis equal or higher;\n not saved."
                    )
                break

        if not updated:
            section_entries.append(entry)
            app.logger.info(
                "New measurement saved: %s for section %s",
                entry, self.selected_section
            )
            self._show_message("Measurement saved.")

        data[self.selected_section] = section_entries
        self.write_data(data)

        # Reset input field
        self.entered_value = ""
        if 'display_value' in self.ids:
            self.ids.display_value.text = ""
        return True

    def save_and_return(self) -> None:
        """
        Save the measurement and return to the appropriate screen.
        Returns to HistoricalDateScreen if in historical mode, otherwise to data_entry.
        """
        if self.save_measurement():
            if self.historical_timestamp:
                self.manager.current = "historical_date"
                self.historical_timestamp = ""
            else:
                self.manager.current = "data_entry"

    @staticmethod
    def load_data() -> dict:
        """
        Load the data from the JSON file in the user data directory.

        :return: The loaded data as a dictionary.
        """
        logger = App.get_running_app().logger
        data_file = get_data_file_path()
        logger.debug("Loading data from %s", data_file)
        if os.path.exists(data_file):
            try:
                with open(data_file, "r") as f:
                    data = json.load(f)
                logger.debug(
                    "Data loaded successfully with %d total entries",
                    sum(len(v) for v in data.values() if isinstance(v, list))
                )
                return data
            except Exception as e:
                logger.exception("Error loading data: %s", e)
        return {}


    @staticmethod
    def write_data(data: dict) -> None:
        """
        Write data to the JSON file in the user data directory.

        :param data: The data dictionary to write.
        """
        logger = App.get_running_app().logger
        data_file = get_data_file_path()
        logger.debug("Writing data to %s", data_file)
        try:
            with open(data_file, "w") as f:
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
    historical_timestamp = StringProperty("")

    def on_pre_enter(self):
        """
        Reset the activity spinner and text input when entering the screen.
        """
        self.ids.activity_level_spinner.text = "Select level"
        self.ids.activity_name_input.text = ""

    def save_activity(self) -> None:
        """
        Save the activity. Return to HistoricalDateScreen if historical_timestamp set,
        else return home.
        """
        level = self.ids.activity_level_spinner.text
        name = self.ids.activity_name_input.text.strip()

        if level == "Select level":
            # no data entered
            target = "historical_date" if self.historical_timestamp else "home"
            self.manager.current = target
            return

        # choose timestamp
        ts = (
            self.historical_timestamp
            if self.historical_timestamp
            else round_up_to_hour(datetime.now())
        )
        entry = {"activity_level": level, "activity_name": name}
        data = MeasurementInputScreen.load_data()
        data.setdefault("activity_data", {}).setdefault(ts, []).append(entry)
        MeasurementInputScreen.write_data(data)

        # clear override and navigate
        target = "historical_date" if self.historical_timestamp else "home"
        self.historical_timestamp = ""
        self.manager.current = target


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
    historical_timestamp = StringProperty("")

    def on_pre_enter(self):
        """
        Load notes for the current hour when the screen is entered.
        """
        ts = self.historical_timestamp or round_up_to_hour(datetime.now())
        data = MeasurementInputScreen.load_data()
        note_text = ""
        if "notes_data" in data and ts in data["notes_data"]:
            note_text = data["notes_data"][ts]
        self.ids.notes_input.text = note_text

    def save_notes(self) -> None:
        """
        Save notes for current (or historical) timestamp and navigate back
        to HistoricalDateScreen if in historical mode, else to home.
        """
        ts = self.historical_timestamp or round_up_to_hour(datetime.now())
        data = MeasurementInputScreen.load_data()
        data.setdefault("notes_data", {})[ts] = self.ids.notes_input.text
        MeasurementInputScreen.write_data(data)


        # go back
        target = "historical_date" if self.historical_timestamp else "home"
        self.historical_timestamp = ""
        self.manager.current = target


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
        if os.path.exists(get_data_file_path()):
            try:
                with open(get_data_file_path(), "r") as f:
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
        if not os.path.exists(get_data_file_path()):
            return

        try:
            with open(get_data_file_path(), "r") as f:
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

    Now includes the calculation of Pain (Arb.) for every hour that has pain data.
    Pain (Arb.) is defined as:
    (average of [RU, RL, LU, LL, Axial, Head] × number of non-zero scores) / 3.
    """

    def on_pre_enter(self):
        """
        Calculate and display statistics including the Pain (Arb.) for each hour.
        """
        self.ids.stats_box.clear_widgets()
        if not os.path.exists(get_data_file_path()):
            self.ids.stats_box.add_widget(Label(text="No data found."))
            return

        try:
            with open(get_data_file_path(), "r") as f:
                data = json.load(f)
            total_entries = 0
            section_averages = {}
            highest_score = -1
            highest_entry = None
            # Current stat calculations for individual sections (excluding sleep data)
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

            # --- Calculate and display Pain (Arb.) per hour ---
            pain_sections = ["RU", "RL", "LU", "LL", "Axial", "Head"]
            # Combine pain data keyed by rounded timestamp.
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

            if combined:
                self.ids.stats_box.add_widget(Label(text="Hourly Pain (Arb.):", font_size="16sp", underline=True))
            # For each hour, calculate the Pain (Arb.) based on available pain scores
            for dt in sorted(combined.keys()):
                vals = combined[dt]
                total = sum(vals[s] for s in pain_sections)
                avg = total / 6.0  # average over six regions (using 0 where missing)
                nonzero_count = sum(1 for s in pain_sections if vals[s] > 0)
                pain_arb = (avg * nonzero_count) / 3.0
                ts_formatted = dt.strftime("%d/%m/%Y %H:%M")
                self.ids.stats_box.add_widget(
                    Label(text=f"{ts_formatted}: Pain (Arb.) = {pain_arb:.2f}", font_size="14sp")
                )
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
    sleep_quality = StringProperty("")
    historical_date = StringProperty("")

    def set_quality(self, quality):
        """
        Set the sleep quality based on the user's selection.

        :param quality: The selected sleep quality.
        :type quality: str
        :return: None
        """
        self.sleep_quality = quality
        self.ids.quality_label.text = f"Quality selected: {quality}"

    def save_sleep_data(self) -> None:
        """
        Validate and save sleep data. Returns to HistoricalDateScreen if historical_date set,
        otherwise to home.
        """
        # determine date
        date_str = self.historical_date or datetime.now().strftime("%Y-%m-%d")

        if not self.ids.hours_input.text and not self.sleep_quality:
            target = "historical_date" if self.historical_date else "home"
            self.manager.current = target
            return

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
            "date": date_str,
            "hours_slept": hours,
            "sleep_quality": int(self.sleep_quality),
        }
        data = self.load_data()
        data.setdefault("sleep_data", []).append(sleep_entry)
        self.write_data(data)

        # confirmation popup
        popup = Popup(
            title="Info",
            content=Label(text="Sleep data saved."),
            size_hint=(None, None),
            size=(dp(300), dp(200)),
            auto_dismiss=True,
        )
        popup.open()

        # reset
        self.ids.hours_input.text = ""
        self.sleep_quality = ""
        self.ids.quality_label.text = ""


        # navigate back
        target = "historical_date" if self.historical_date else "home"
        self.historical_date = ""
        self.manager.current = target

    @staticmethod
    def load_data():
        """
        Load sleep data from the JSON file.

        :return: The loaded data as a dictionary.
        :rtype: dict
        """
        if os.path.exists(get_data_file_path()):
            with open(get_data_file_path(), "r") as f:
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
        with open(get_data_file_path(), "w") as f:
            json.dump(data, f, indent=2)


class CalendarScreen(Screen):
    """
    Screen displaying a calendar view of available days.

    The screen collects all dates for which there is pain, activity, note or sleep data.
    Tapping a day navigates to the DayDetailScreen.
    """

    def on_pre_enter(self):
        """
        Populate the calendar with available days.
        """
        # Clear previous entries in the container (assumed to have id "calendar_box" in KV)
        self.ids.calendar_box.clear_widgets()
        data = MeasurementInputScreen.load_data()  # Load all data from JSON
        dates_set = set()

        # From pain measurements in each pain section.
        pain_sections = ["RU", "RL", "LU", "LL", "Axial", "Head"]
        for sec in pain_sections:
            if sec in data and isinstance(data[sec], list):
                for entry in data[sec]:
                    try:
                        dt = datetime.strptime(entry["timestamp"], "%Y-%m-%d %H:%M:%S")
                        dates_set.add(dt.date())
                    except Exception:
                        continue

        # From activity data (keys are timestamps).
        if "activity_data" in data:
            for ts in data["activity_data"].keys():
                try:
                    dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                    dates_set.add(dt.date())
                except Exception:
                    continue

        # From notes data.
        if "notes_data" in data:
            for ts in data["notes_data"].keys():
                try:
                    dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                    dates_set.add(dt.date())
                except Exception:
                    continue

        # From sleep data (using the 'date' field).
        if "sleep_data" in data:
            for entry in data["sleep_data"]:
                try:
                    dt = datetime.strptime(entry.get("date", ""), "%Y-%m-%d").date()
                    dates_set.add(dt)
                except Exception:
                    continue

        # Sort dates in ascending order.
        sorted_dates = sorted(list(dates_set))
        app = App.get_running_app()
        total = len(sorted_dates)
        for idx, d in enumerate(sorted_dates):
            btn = Button(text=d.strftime("%Y-%m-%d"),
                         size_hint_y=None,
                         height="40dp",
                         background_normal="",
                         background_color=app.get_rainbow_colour(idx, total, 0.7),
                         color=(1, 1, 1, 1))
            btn.bind(on_release=lambda instance, d=d: self.select_date(d))
            self.ids.calendar_box.add_widget(btn)

    def select_date(self, date_obj):
        """
        Handle a day selection; pass the selected date to DayDetailScreen and change screen.

        :param date_obj: The selected date as a datetime.date object.
        """
        day_screen = self.manager.get_screen("day_detail")
        day_screen.selected_date = date_obj.strftime("%Y-%m-%d")
        self.manager.current = "day_detail"


class DayDetailScreen(Screen):
    """
    Screen displaying the details for a specific day.

    The screen shows sleep data (if available) at the top and then a list of available hours.
    Tapping an hour brings up HourDetailScreen.
    """
    selected_date = StringProperty("")

    def on_pre_enter(self):
        """
        Populate the day detail view with sleep data and a list of available hours.
        """
        self.ids.day_box.clear_widgets()
        data = MeasurementInputScreen.load_data()

        # Display sleep data for this day (if available).
        sleep_text = ""
        if "sleep_data" in data:
            sleep_entries = [entry for entry in data["sleep_data"] if entry.get("date") == self.selected_date]
            if sleep_entries:
                # Assume the last recorded sleep entry for that day is most relevant.
                entry = sleep_entries[-1]
                sleep_text = f"Sleep: {entry.get('hours_slept', '')} hrs, Quality: {entry.get('sleep_quality', '')}"
        if sleep_text:
            sleep_label = Label(text=sleep_text, font_size="14sp", size_hint_y=None, height="30dp")
            self.ids.day_box.add_widget(sleep_label)

        # Gather available hours from pain measurements, activity and notes.
        available_hours = set()
        pain_sections = ["RU", "RL", "LU", "LL", "Axial", "Head"]
        for sec in pain_sections:
            if sec in data and isinstance(data[sec], list):
                for entry in data[sec]:
                    try:
                        dt = datetime.strptime(entry["timestamp"], "%Y-%m-%d %H:%M:%S")
                        if dt.strftime("%Y-%m-%d") == self.selected_date:
                            available_hours.add(dt.hour)
                    except Exception:
                        continue

        # Also include hours from activity_data.
        if "activity_data" in data:
            for ts in data["activity_data"].keys():
                try:
                    dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                    if dt.strftime("%Y-%m-%d") == self.selected_date:
                        available_hours.add(dt.hour)
                except Exception:
                    continue

        # And from notes_data.
        if "notes_data" in data:
            for ts in data["notes_data"].keys():
                try:
                    dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                    if dt.strftime("%Y-%m-%d") == self.selected_date:
                        available_hours.add(dt.hour)
                except Exception:
                    continue

        sorted_hours = sorted(list(available_hours))
        app = App.get_running_app()
        if sorted_hours:
            total = len(sorted_hours)
            for idx, hr in enumerate(sorted_hours):
                hr_text = f"{hr:02d}:00"
                btn = Button(text=hr_text,
                             size_hint_y=None,
                             height="40dp",
                             background_normal="",
                             background_color=app.get_rainbow_colour(idx, total, 0.7),
                             color=(1, 1, 1, 1)
                             )
                btn.bind(on_release=lambda inst, hr=hr: self.select_hour(hr))
                self.ids.day_box.add_widget(btn, index=0)
        else:
            self.ids.day_box.add_widget(Label(text="No hour data available for this day.", font_size="14sp"))
        # Back button to return to the calendar view.
        back_btn = Button(text="Back",
                          size_hint_y=None,
                          height="40dp",
                          background_normal="",
                          background_color=app.get_rainbow_colour(0, 6),
                          color=(1, 1, 1, 1)
                          )
        back_btn.bind(on_release=lambda x: setattr(self.manager, "current", "calendar"))
        self.ids.day_box.add_widget(back_btn)

    def select_hour(self, hour):
        """
        Handle an hour selection; pass the selected hour to HourDetailScreen and change screen.

        :param hour: The selected hour as an integer.
        """
        hour_screen = self.manager.get_screen("hour_detail")
        hour_screen.selected_date = self.selected_date
        # Format hour as "HH:00" (we assume that saved timestamps are rounded to the hour).
        hour_screen.selected_hour = f"{hour:02d}:00"
        self.manager.current = "hour_detail"


class HourDetailScreen(Screen):
    """
    Screen displaying detailed data for a specific hour.

    Shows pain readings (in the order: RU, RL, LU, LL, Axial, Head),
    followed by activity data (both level and name) and any note.
    """
    selected_date = StringProperty("")
    selected_hour = StringProperty("")

    def on_pre_enter(self):
        """
        Populate the detail view for the selected hour.
        """
        self.ids.hour_box.clear_widgets()
        # Construct the full timestamp key (assumed stored as "YYYY-mm-dd HH:00:00").
        timestamp_key = f"{self.selected_date} {self.selected_hour}:00"
        data = MeasurementInputScreen.load_data()
        pain_sections = ["RU", "RL", "LU", "LL", "Axial", "Head"]
        detail_values = {}

        # Retrieve pain measurements.
        for sec in pain_sections:
            detail_values[sec] = ""
            if sec in data and isinstance(data[sec], list):
                for entry in data[sec]:
                    if entry.get("timestamp") == timestamp_key:
                        detail_values[sec] = entry.get("value", "")
                        break

        # Retrieve activity data.
        activity_levels = []
        activity_names = []
        if "activity_data" in data:
            for ts, entries in data["activity_data"].items():
                if ts == timestamp_key:
                    for entry in entries:
                        activity_levels.append(str(entry.get("activity_level", "")))
                        activity_names.append(entry.get("activity_name", ""))
        # Retrieve notes.
        note_text = ""
        if "notes_data" in data:
            for ts, note in data["notes_data"].items():
                if ts == timestamp_key:
                    note_text = note
                    break

        # Display pain data.
        for sec in pain_sections:
            lbl = Label(text=f"{sec}: {detail_values[sec]}", font_size="14sp", size_hint_y=None, height="30dp")
            self.ids.hour_box.add_widget(lbl)

        # Display activity data, if available.
        if activity_levels or activity_names:
            act_val_str = f"[{','.join(activity_levels)}]" if activity_levels else ""
            act_names_str = f"[{','.join(activity_names)}]" if activity_names else ""
            self.ids.hour_box.add_widget(Label(text=f"Activity Value: {act_val_str}", font_size="14sp",
                                               size_hint_y=None, height="30dp"))
            self.ids.hour_box.add_widget(Label(text=f"Activity: {act_names_str}", font_size="14sp",
                                               size_hint_y=None, height="30dp"))
        # Display note.
        if note_text.strip():
            self.ids.hour_box.add_widget(Label(text=f"Note: {note_text}", font_size="14sp",
                                               size_hint_y=None, height="30dp"))
        # Back button to return to the day view.
        app = App.get_running_app()
        back_btn = Button(text="Back",
                          size_hint_y=None,
                          height="40dp",
                          background_normal="",
                          background_color=app.get_rainbow_colour(0, 6),
                          color=(1, 1, 1, 1)
                          )
        back_btn.bind(on_release=lambda x: setattr(self.manager, "current", "day_detail"))
        self.ids.hour_box.add_widget(back_btn)

class LogScreen(Screen):
    """
    Screen for viewing the application log.

    The log file (app.log) is read from the app's user data directory.
    Its contents are displayed in a scrollable, read-only TextInput.
    """

    def on_pre_enter(self):
        """
        Load the log file content before the screen is displayed.
        """
        log_file = os.path.join(App.get_running_app().user_data_dir, "app.log")
        try:
            with open(log_file, "r") as f:
                log_content = f.read()
        except Exception as e:
            log_content = f"Error reading log file: {e}"
        # Set the content of the TextInput with id 'log_output'.
        self.ids.log_output.text = log_content

    def clear_log(self):
        """
        Clear the log file (if desired) and update the view.
        """
        log_file = os.path.join(App.get_running_app().user_data_dir, "app.log")
        try:
            with open(log_file, "w") as f:
                f.write("")
            self.ids.log_output.text = ""
        except Exception as e:
            self.ids.log_output.text = f"Error clearing log file: {e}"


class HistoricalDateScreen(Screen):
    """
    First step for historical entry: pick a date and hour,
    then jump to one of the existing entry screens.
    """
    date_str = StringProperty("")    # holds YYYY-MM-DD
    hour_str = StringProperty("")    # holds HH:MM

    def on_pre_enter(self) -> None:
        """
        Initialise date_str / hour_str if not already set,
        and push those values into the widgets.
        """
        # if no date yet chosen, default to today
        if not self.date_str:
            self.date_str = datetime.now().strftime("%Y-%m-%d")
        # if no hour yet chosen, default to midnight
        if not self.hour_str:
            self.hour_str = "00:00"

        # push into UI
        self.ids.date_input.text = self.date_str
        self.ids.hour_spinner.text = self.hour_str

    def go_to_pain(self) -> None:
        """Navigate to the pain‐entry screen with our chosen timestamp."""
        inp = self.manager.get_screen("input_screen")
        inp.historical_timestamp = f"{self.ids.date_input.text} {self.ids.hour_spinner.text}:00"
        inp.selected_section = "RU"  # or let them pick inside?
        inp.ids.section_label.text = (
            f"Enter measurement for RU at {inp.historical_timestamp}"
        )
        inp.entered_value = ""
        inp.ids.display_value.text = ""
        inp.ids.status_label.text = ""
        self.manager.current = "input_screen"

    def go_to_activity(self) -> None:
        act = self.manager.get_screen("activity")
        act.historical_timestamp = f"{self.ids.date_input.text} {self.ids.hour_spinner.text}:00"
        act.ids.activity_level_spinner.text = "Select level"
        act.ids.activity_name_input.text = ""
        self.manager.current = "activity"

    def go_to_sleep(self) -> None:
        sl = self.manager.get_screen("sleep_input")
        sl.historical_date = self.ids.date_input.text
        sl.ids.hours_input.text = ""
        sl.ids.quality_label.text = "Quality selected: None"
        sl.sleep_quality = ""
        self.manager.current = "sleep_input"

    def go_to_notes(self) -> None:
        nt = self.manager.get_screen("notes")
        nt.historical_timestamp = f"{self.ids.date_input.text} {self.ids.hour_spinner.text}:00"
        nt.ids.notes_input.text = ""
        self.manager.current = "notes"


class MeasurementApp(App):
    """
    Main application class.
    """

    def build(self):
        """
        Build the application UI, set up logging, request storage permissions if needed,
        and initialise the screen manager.

        :return: The root widget (ScreenManager).
        :rtype: ScreenManager
        """
        Builder.load_file("main.kv")
        self.setup_logger()
        if platform == 'android':
            try:
                request_permissions([Permission.WRITE_EXTERNAL_STORAGE,
                                     Permission.READ_EXTERNAL_STORAGE,
                                     Permission.MANAGE_EXTERNAL_STORAGE])
                self.logger.info("Storage permissions requested.")
            except Exception as e:
                self.logger.error("Error requesting permissions: %s", e)
        sm = ScreenManager()
        sm.add_widget(HomeScreen(name="home"))
        sm.add_widget(DataEntryScreen(name="data_entry"))
        sm.add_widget(MeasurementInputScreen(name="input_screen"))
        sm.add_widget(CalendarScreen(name="calendar"))
        sm.add_widget(DayDetailScreen(name="day_detail"))
        sm.add_widget(HourDetailScreen(name="hour_detail"))
        sm.add_widget(PlotScreen(name="plot_screen"))
        sm.add_widget(StatsScreen(name="stats_screen"))
        sm.add_widget(SleepInputScreen(name="sleep_input"))
        sm.add_widget(ActivityScreen(name="activity"))
        sm.add_widget(NotesScreen(name="notes"))
        sm.add_widget(LogScreen(name="log"))
        sm.add_widget(HistoricalDateScreen(name="historical_date"))
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
        fh = logging.FileHandler(log_file, mode='a')
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
    def get_rainbow_colour(index, total, alpha=0.7):
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
        Timestamp (dd/mm/yyyy hh:mm), Activity Value, Activity, RU, RL, LU, LL, Axial, Head, Notes.
        Sleep data is appended separately.
        The CSV file is saved to the Downloads folder.

        :return: The absolute path to the saved CSV file.
        :rtype: str
        """
        logger = App.get_running_app().logger
        logger.debug("Exporting CSV with updated format to Downloads folder.")
        # Load data from JSON file
        if os.path.exists(get_data_file_path()):
            with open(get_data_file_path(), "r") as f:
                data = json.load(f)
        else:
            data = {}

        # Define pain sections in desired order.
        pain_sections = ["RU", "RL", "LU", "LL", "Axial", "Head"]
        # Build combined rows keyed by rounded timestamp.
        combined_rows = {}
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

        # Determine export directory (Downloads folder)
        if platform == 'android' and storagepath:
            export_dir = storagepath.get_downloads_dir()
            if not export_dir:
                export_dir = App.get_running_app().user_data_dir
        else:
            export_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        os.makedirs(export_dir, exist_ok=True)
        csv_path = os.path.join(export_dir, "pain_management.csv")
        if os.path.exists(csv_path):
            os.remove(csv_path)

        try:
            with open(csv_path, "w", newline="") as csvfile:
                writer = csv.writer(csvfile)
                header = ["Timestamp (dd/mm/yyyy hh:mm)", "Activity Value", "Activity",
                          "RU", "RL", "LU", "LL", "Axial", "Head", "Notes"]
                writer.writerow(header)
                for dt in sorted(combined_rows.keys()):
                    ts_formatted = dt.strftime("%d/%m/%Y %H:%M")
                    act_levels = combined_rows[dt]["activity_levels"]
                    act_names = combined_rows[dt]["activity_names"]
                    act_val_str = f"[{','.join(act_levels)}]" if act_levels else ""
                    act_names_str = f"[{','.join(act_names)}]" if act_names else ""
                    pain_vals = [combined_rows[dt]["pain"].get(sec, "") for sec in pain_sections]
                    note_val = combined_rows[dt]["notes"]
                    row = [ts_formatted, act_val_str, act_names_str] + pain_vals + [note_val]
                    writer.writerow(row)
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

    def export_popup(self):
        """
        Display a popup indicating the CSV export location.
        """
        path = self.export_csv_to_internal()
        layout = BoxLayout(orientation='vertical', padding=20, spacing=10)
        scroll = None
        try:
            from kivy.uix.scrollview import ScrollView
            scroll = ScrollView(size_hint=(1, None), size=("260dp", "100dp"))
        except Exception:
            pass
        inner_layout = BoxLayout(orientation='vertical', padding=(20, 50), size_hint_y=None)
        message = Label(text=f"{path}", halign="left", valign="middle", size_hint_y=None)
        message.bind(width=lambda instance, value: setattr(instance, 'text_size', (value, None)))
        message.bind(texture_size=lambda instance, value: setattr(instance, 'height', value[1]))
        inner_layout.add_widget(message)
        inner_layout.bind(minimum_height=inner_layout.setter('height'))
        if scroll:
            scroll.add_widget(inner_layout)
            layout.add_widget(scroll)
        else:
            layout.add_widget(inner_layout)
        buttons = BoxLayout(spacing=50, size_hint_y=None, height="48dp")
        confirm_btn = Button(text="OK", background_color=(0.8, 0.1, 0.1, 1))
        buttons.add_widget(confirm_btn)
        layout.add_widget(buttons)
        popup = Popup(title="CSV Exported To:", content=layout,
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
        cancel_btn = Button(text="Cancel", background_color=(0, 1, 0, 0.6))
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
        if os.path.exists(get_data_file_path()):
            os.remove(get_data_file_path())
            logger.info("Data file '%s' deleted.", get_data_file_path())
        else:
            logger.warning("Attempt to delete non-existent data file.")
        popup.dismiss()


if __name__ == "__main__":
    MeasurementApp().run()
